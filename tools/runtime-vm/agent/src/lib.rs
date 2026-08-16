#![allow(non_snake_case)]

use std::ffi::c_void;
use std::ptr::{null, null_mut};
use windows_sys::Win32::Foundation::{CloseHandle, GetLastError, HANDLE, HINSTANCE, INVALID_HANDLE_VALUE};
use windows_sys::Win32::System::LibraryLoader::DisableThreadLibraryCalls;
use windows_sys::Win32::System::Pipes::{ConnectNamedPipe, CreateNamedPipeW, DisconnectNamedPipe, PIPE_READMODE_BYTE, PIPE_TYPE_BYTE, PIPE_WAIT};
use windows_sys::Win32::System::SystemServices::{DLL_PROCESS_ATTACH, DLL_PROCESS_DETACH};
use windows_sys::Win32::System::Threading::{CreateThread, GetCurrentProcessId};
use windows_sys::Win32::Storage::FileSystem::{ReadFile, WriteFile, PIPE_ACCESS_DUPLEX};

fn wide(value: &str) -> Vec<u16> {
    value.encode_utf16().chain(std::iter::once(0)).collect()
}

fn pipe_name() -> Vec<u16> {
    wide(&format!(r"\\.\pipe\sc2-gsvm-agent-{}", unsafe { GetCurrentProcessId() }))
}

fn write_response(pipe: HANDLE, response: &str) {
    let payload = format!("{response}\n");
    let mut written = 0u32;
    let _ = unsafe { WriteFile(pipe, payload.as_ptr(), payload.len() as u32, &mut written, null_mut()) };
}

fn response(command: &str) -> &'static str {
    match command.trim() {
        "HELLO" => r#"{"protocol":"gsvm-agent/1","agent_version":"0.1.0","hook_enabled":false,"state":"ready"}"#,
        "STATUS" => r#"{"protocol":"gsvm-agent/1","hook_enabled":false,"state":"ready","vm_hook":"disabled"}"#,
        "SHUTDOWN" => r#"{"protocol":"gsvm-agent/1","hook_enabled":false,"state":"stopping"}"#,
        _ => r#"{"protocol":"gsvm-agent/1","hook_enabled":false,"error":"unknown_command"}"#,
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
        let connected = ConnectNamedPipe(pipe, null_mut()) != 0 || GetLastError() == ERROR_PIPE_CONNECTED;
        if connected {
            loop {
                let mut buffer = [0u8; 256];
                let mut read = 0u32;
                if ReadFile(pipe, buffer.as_mut_ptr(), buffer.len() as u32, &mut read, null_mut()) == 0 {
                    break;
                }
                let command = String::from_utf8_lossy(&buffer[..read as usize]);
                let should_stop = command.trim() == "SHUTDOWN";
                write_response(pipe, response(&command));
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
pub unsafe extern "system" fn DllMain(module: HINSTANCE, reason: u32, _reserved: *mut c_void) -> i32 {
    if reason == DLL_PROCESS_ATTACH {
        DisableThreadLibraryCalls(module);
        let thread = CreateThread(null(), 0, Some(server_thread), null_mut(), 0, null_mut());
        if !thread.is_null() {
            CloseHandle(thread);
        }
    } else if reason == DLL_PROCESS_DETACH {
        // No VM hook or process-wide teardown is installed in the handshake stage.
    }
    1
}
