#![allow(non_snake_case)]

use std::ffi::c_void;
use std::ptr::{null, null_mut};
use std::sync::atomic::{AtomicBool, AtomicPtr, AtomicU32, AtomicU64, Ordering};
use windows_sys::Win32::Foundation::{
    CloseHandle, GetLastError, HANDLE, HINSTANCE, INVALID_HANDLE_VALUE,
};
use windows_sys::Win32::Storage::FileSystem::{ReadFile, WriteFile, PIPE_ACCESS_DUPLEX};
use windows_sys::Win32::System::Diagnostics::Debug::{
    AddVectoredExceptionHandler, RaiseException, RemoveVectoredExceptionHandler,
    EXCEPTION_CONTINUE_EXECUTION, EXCEPTION_CONTINUE_SEARCH, EXCEPTION_POINTERS,
};
use windows_sys::Win32::System::LibraryLoader::DisableThreadLibraryCalls;
use windows_sys::Win32::System::Pipes::{
    ConnectNamedPipe, CreateNamedPipeW, DisconnectNamedPipe, PIPE_READMODE_BYTE, PIPE_TYPE_BYTE,
    PIPE_WAIT,
};
use windows_sys::Win32::System::SystemServices::{DLL_PROCESS_ATTACH, DLL_PROCESS_DETACH};
use windows_sys::Win32::System::Threading::{CreateThread, GetCurrentProcessId};

fn wide(value: &str) -> Vec<u16> {
    value.encode_utf16().chain(std::iter::once(0)).collect()
}

fn pipe_name() -> Vec<u16> {
    wide(&format!(r"\\.\pipe\sc2-gsvm-agent-{}", unsafe {
        GetCurrentProcessId()
    }))
}

static TRACE_ARMED: AtomicBool = AtomicBool::new(false);
static TRACE_HANDLER: AtomicPtr<c_void> = AtomicPtr::new(null_mut());
static TRACE_BREAKPOINT_COUNT: AtomicU64 = AtomicU64::new(0);
static TRACE_LAST_EXCEPTION: AtomicU32 = AtomicU32::new(0);
static TRACE_LAST_IP: AtomicU64 = AtomicU64::new(0);

unsafe extern "system" fn trace_exception_handler(info: *mut EXCEPTION_POINTERS) -> i32 {
    if !TRACE_ARMED.load(Ordering::Acquire) || info.is_null() {
        return EXCEPTION_CONTINUE_SEARCH;
    }
    let record = (*info).ExceptionRecord;
    if record.is_null() || !matches!((*record).ExceptionCode as u32, 0x80000003 | 0xE0424242) {
        return EXCEPTION_CONTINUE_SEARCH;
    }
    TRACE_BREAKPOINT_COUNT.fetch_add(1, Ordering::AcqRel);
    TRACE_LAST_EXCEPTION.store((*record).ExceptionCode as u32, Ordering::Release);
    let context = (*info).ContextRecord;
    if !context.is_null() {
        TRACE_LAST_IP.store((*context).Rip, Ordering::Release);
    }
    EXCEPTION_CONTINUE_EXECUTION
}

fn trace_arm() -> String {
    if TRACE_ARMED.swap(true, Ordering::AcqRel) {
        return r#"{"trace_enabled":true,"trace_mode":"veh-breakpoint","state":"already_armed"}"#
            .to_string();
    }
    let handler = unsafe { AddVectoredExceptionHandler(1, Some(trace_exception_handler)) };
    if handler.is_null() {
        TRACE_ARMED.store(false, Ordering::Release);
        return r#"{"trace_enabled":false,"trace_mode":"veh-breakpoint","error":"install_failed"}"#
            .to_string();
    }
    TRACE_HANDLER.store(handler, Ordering::Release);
    r#"{"trace_enabled":true,"trace_mode":"veh-breakpoint","state":"armed"}"#.to_string()
}

fn trace_disarm() -> String {
    TRACE_ARMED.store(false, Ordering::Release);
    let handler = TRACE_HANDLER.swap(null_mut(), Ordering::AcqRel);
    if !handler.is_null() {
        unsafe {
            RemoveVectoredExceptionHandler(handler);
        }
    }
    r#"{"trace_enabled":false,"trace_mode":"veh-breakpoint","state":"disarmed"}"#.to_string()
}

fn trace_status() -> String {
    format!(
        r#"{{"trace_enabled":{},"trace_mode":"veh-breakpoint","breakpoint_count":{},"last_exception":{},"last_ip":"0x{:016X}"}}"#,
        TRACE_ARMED.load(Ordering::Acquire),
        TRACE_BREAKPOINT_COUNT.load(Ordering::Acquire),
        TRACE_LAST_EXCEPTION.load(Ordering::Acquire),
        TRACE_LAST_IP.load(Ordering::Acquire),
    )
}

fn write_response(pipe: HANDLE, response: &str) {
    let payload = format!("{response}\n");
    let mut written = 0u32;
    let _ = unsafe {
        WriteFile(
            pipe,
            payload.as_ptr(),
            payload.len() as u32,
            &mut written,
            null_mut(),
        )
    };
}

fn response(command: &str) -> String {
    match command.trim() {
        "HELLO" => r#"{"protocol":"gsvm-agent/1","agent_version":"0.2.0","hook_enabled":false,"state":"ready","trace_mode":"veh-breakpoint"}"#.to_string(),
        "STATUS" => format!(r#"{{"protocol":"gsvm-agent/1","hook_enabled":false,"state":"ready","vm_hook":"disabled","trace":{}}}"#, trace_status()),
        "TRACE_ARM" => trace_arm(),
        "TRACE_STATUS" => trace_status(),
        "TRACE_TEST_BREAK" => {
            if !TRACE_ARMED.load(Ordering::Acquire) {
                r#"{"trace_enabled":false,"error":"trace_not_armed"}"#.to_string()
            } else {
                unsafe { RaiseException(0xE0424242, 0, 0, null()); }
                trace_status()
            }
        }
        "TRACE_TEST_INT3" => {
            if !TRACE_ARMED.load(Ordering::Acquire) {
                r#"{"trace_enabled":false,"error":"trace_not_armed"}"#.to_string()
            } else {
                unsafe { RaiseException(0x80000003, 0, 0, null()); }
                trace_status()
            }
        }
        "TRACE_DISARM" => trace_disarm(),
        "SHUTDOWN" => {
            let _ = trace_disarm();
            r#"{"protocol":"gsvm-agent/1","hook_enabled":false,"state":"stopping"}"#.to_string()
        }
        _ => r#"{"protocol":"gsvm-agent/1","hook_enabled":false,"error":"unknown_command"}"#.to_string(),
    }
}

unsafe extern "system" fn server_thread(_parameter: *mut c_void) -> u32 {
    let name = pipe_name();
    loop {
        let pipe = CreateNamedPipeW(
            name.as_ptr(),
            PIPE_ACCESS_DUPLEX,
            PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT,
            1,
            4096,
            4096,
            0,
            null(),
        );
        if pipe == INVALID_HANDLE_VALUE {
            return 1;
        }
        let connected =
            ConnectNamedPipe(pipe, null_mut()) != 0 || GetLastError() == ERROR_PIPE_CONNECTED;
        if connected {
            loop {
                let mut buffer = [0u8; 256];
                let mut read = 0u32;
                if ReadFile(
                    pipe,
                    buffer.as_mut_ptr(),
                    buffer.len() as u32,
                    &mut read,
                    null_mut(),
                ) == 0
                {
                    break;
                }
                let command = String::from_utf8_lossy(&buffer[..read as usize]);
                let should_stop = command.trim() == "SHUTDOWN";
                let reply = response(&command);
                write_response(pipe, &reply);
                if should_stop {
                    DisconnectNamedPipe(pipe);
                    CloseHandle(pipe);
                    return 0;
                }
            }
        }
        DisconnectNamedPipe(pipe);
        CloseHandle(pipe);
    }
}

const ERROR_PIPE_CONNECTED: u32 = 535;

#[no_mangle]
pub unsafe extern "system" fn DllMain(
    module: HINSTANCE,
    reason: u32,
    _reserved: *mut c_void,
) -> i32 {
    if reason == DLL_PROCESS_ATTACH {
        DisableThreadLibraryCalls(module);
        let thread = CreateThread(null(), 0, Some(server_thread), null_mut(), 0, null_mut());
        if !thread.is_null() {
            CloseHandle(thread);
        }
    } else if reason == DLL_PROCESS_DETACH {
        let _ = trace_disarm();
    }
    1
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn trace_protocol_captures_int3_and_disarms() {
        let _ = trace_disarm();
        TRACE_BREAKPOINT_COUNT.store(0, Ordering::Release);
        TRACE_LAST_EXCEPTION.store(0, Ordering::Release);
        TRACE_LAST_IP.store(0, Ordering::Release);

        let armed = trace_arm();
        assert!(armed.contains(r#""trace_enabled":true"#));
        assert_eq!(TRACE_BREAKPOINT_COUNT.load(Ordering::Acquire), 0);

        let trace_response = response("TRACE_TEST_INT3");
        assert!(trace_response.contains(r#""last_exception":2147483651"#));
        assert_eq!(TRACE_BREAKPOINT_COUNT.load(Ordering::Acquire), 1);
        assert_ne!(TRACE_LAST_IP.load(Ordering::Acquire), 0);

        let disarmed = trace_disarm();
        assert!(disarmed.contains(r#""trace_enabled":false"#));
        assert!(!TRACE_ARMED.load(Ordering::Acquire));
        assert!(response("TRACE_TEST_INT3").contains("trace_not_armed"));
    }
}
