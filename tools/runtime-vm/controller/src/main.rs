use std::env;
use std::ffi::{c_void, OsStr};
use std::fs;
use std::iter::once;
use std::os::windows::ffi::OsStrExt;
use std::path::{Path, PathBuf};
use std::ptr::{null, null_mut};
use std::thread;
use std::time::{Duration, Instant};
use windows_sys::Win32::Foundation::{
    CloseHandle, GetLastError, HANDLE, INVALID_HANDLE_VALUE, WAIT_OBJECT_0,
};
use windows_sys::Win32::Storage::FileSystem::{
    CreateFileW, ReadFile, WriteFile, FILE_ATTRIBUTE_NORMAL, FILE_GENERIC_READ, FILE_GENERIC_WRITE,
    OPEN_EXISTING,
};
use windows_sys::Win32::System::LibraryLoader::{GetModuleHandleW, GetProcAddress};
use windows_sys::Win32::System::Memory::{
    VirtualAllocEx, VirtualFreeEx, MEM_COMMIT, MEM_RELEASE, MEM_RESERVE, PAGE_READWRITE,
};
use windows_sys::Win32::System::Pipes::{WaitNamedPipeW, NMPWAIT_WAIT_FOREVER};
use windows_sys::Win32::System::Threading::{
    CreateRemoteThread, GetExitCodeThread, OpenProcess, WaitForSingleObject, PROCESS_CREATE_THREAD,
    PROCESS_QUERY_LIMITED_INFORMATION, PROCESS_VM_OPERATION, PROCESS_VM_READ, PROCESS_VM_WRITE,
};

const PROTOCOL: &str = "gsvm-agent/1";

struct Profile {
    schema_version: u32,
    executable_name: String,
    sha256: String,
    hook_enabled: bool,
}

fn json_string(source: &str, key: &str) -> Result<String, String> {
    let marker = format!("\"{key}\"");
    let start = source
        .find(&marker)
        .ok_or_else(|| format!("profile key missing: {key}"))?;
    let rest = &source[start + marker.len()..];
    let colon = rest
        .find(':')
        .ok_or_else(|| format!("profile key malformed: {key}"))?;
    let value = rest[colon + 1..].trim_start();
    if !value.starts_with('"') {
        return Err(format!("profile key is not a string: {key}"));
    }
    let end = value[1..]
        .find('"')
        .ok_or_else(|| format!("profile string unterminated: {key}"))?
        + 1;
    Ok(value[1..end].to_string())
}

fn json_u32(source: &str, key: &str) -> Result<u32, String> {
    let marker = format!("\"{key}\"");
    let start = source
        .find(&marker)
        .ok_or_else(|| format!("profile key missing: {key}"))?;
    let rest = &source[start + marker.len()..];
    let colon = rest
        .find(':')
        .ok_or_else(|| format!("profile key malformed: {key}"))?;
    rest[colon + 1..]
        .trim_start()
        .split(|ch: char| !ch.is_ascii_digit())
        .next()
        .unwrap_or("")
        .parse()
        .map_err(|_| format!("profile key is not a number: {key}"))
}

fn json_bool(source: &str, key: &str) -> Result<bool, String> {
    let marker = format!("\"{key}\"");
    let start = source
        .find(&marker)
        .ok_or_else(|| format!("profile key missing: {key}"))?;
    let rest = &source[start + marker.len()..];
    let colon = rest
        .find(':')
        .ok_or_else(|| format!("profile key malformed: {key}"))?;
    let value = rest[colon + 1..].trim_start();
    if value.starts_with("true") {
        Ok(true)
    } else if value.starts_with("false") {
        Ok(false)
    } else {
        Err(format!("profile key is not boolean: {key}"))
    }
}

fn parse_profile(source: &str) -> Result<Profile, String> {
    Ok(Profile {
        schema_version: json_u32(source, "schema_version")?,
        executable_name: json_string(source, "executable_name")?,
        sha256: json_string(source, "sha256")?,
        hook_enabled: json_bool(source, "hook_enabled")?,
    })
}

fn wide(value: impl AsRef<OsStr>) -> Vec<u16> {
    value.as_ref().encode_wide().chain(once(0)).collect()
}

fn pipe_name(pid: u32) -> String {
    format!(r"\\.\pipe\sc2-gsvm-agent-{pid}")
}

fn usage() -> ! {
    eprintln!("usage: gsvm-controller inject --pid PID --dll DLL --profile PROFILE --ack-debug-process [--arm-trace] [--test-break|--test-int3] [--hold-trace-ms N] [--timeout-ms N]");
    std::process::exit(2)
}

fn arg_value(args: &[String], name: &str) -> Option<String> {
    args.windows(2)
        .find(|pair| pair[0] == name)
        .map(|pair| pair[1].clone())
}

fn has_arg(args: &[String], name: &str) -> bool {
    args.iter().any(|item| item == name)
}

fn sha256(path: &Path) -> Result<String, String> {
    let data = fs::read(path).map_err(|err| format!("read target failed: {err}"))?;
    Ok(sha256_bytes(&data))
}

fn sha256_bytes(data: &[u8]) -> String {
    const K: [u32; 64] = [
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4,
        0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe,
        0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f,
        0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
        0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
        0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
        0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116,
        0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
        0xc67178f2,
    ];
    let mut msg = data.to_vec();
    let bit_len = (msg.len() as u64) * 8;
    msg.push(0x80);
    while msg.len() % 64 != 56 {
        msg.push(0);
    }
    msg.extend_from_slice(&bit_len.to_be_bytes());
    let mut h = [
        0x6a09e667u32,
        0xbb67ae85,
        0x3c6ef372,
        0xa54ff53a,
        0x510e527f,
        0x9b05688c,
        0x1f83d9ab,
        0x5be0cd19,
    ];
    for chunk in msg.chunks_exact(64) {
        let mut w = [0u32; 64];
        for i in 0..16 {
            w[i] = u32::from_be_bytes([
                chunk[i * 4],
                chunk[i * 4 + 1],
                chunk[i * 4 + 2],
                chunk[i * 4 + 3],
            ]);
        }
        for i in 16..64 {
            let s0 = w[i - 15].rotate_right(7) ^ w[i - 15].rotate_right(18) ^ (w[i - 15] >> 3);
            let s1 = w[i - 2].rotate_right(17) ^ w[i - 2].rotate_right(19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16]
                .wrapping_add(s0)
                .wrapping_add(w[i - 7])
                .wrapping_add(s1);
        }
        let (mut a, mut b, mut c, mut d, mut e, mut f, mut g, mut hh) =
            (h[0], h[1], h[2], h[3], h[4], h[5], h[6], h[7]);
        for i in 0..64 {
            let s1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
            let ch = (e & f) ^ ((!e) & g);
            let t1 = hh
                .wrapping_add(s1)
                .wrapping_add(ch)
                .wrapping_add(K[i])
                .wrapping_add(w[i]);
            let s0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
            let maj = (a & b) ^ (a & c) ^ (b & c);
            let t2 = s0.wrapping_add(maj);
            hh = g;
            g = f;
            f = e;
            e = d.wrapping_add(t1);
            d = c;
            c = b;
            b = a;
            a = t1.wrapping_add(t2);
        }
        for (slot, value) in h.iter_mut().zip([a, b, c, d, e, f, g, hh]) {
            *slot = slot.wrapping_add(value);
        }
    }
    h.iter().map(|value| format!("{value:08X}")).collect()
}

fn json_quote(value: &str) -> String {
    let escaped = value.replace('\\', "\\\\").replace('"', "\\\"");
    format!("\"{escaped}\"")
}

fn query_image_path(process: HANDLE) -> Result<PathBuf, String> {
    let mut capacity = 32768u32;
    let mut buffer = vec![0u16; capacity as usize];
    let ok = unsafe {
        windows_sys::Win32::System::Threading::QueryFullProcessImageNameW(
            process,
            0,
            buffer.as_mut_ptr(),
            &mut capacity,
        )
    };
    if ok == 0 {
        return Err(format!("QueryFullProcessImageNameW failed: {}", unsafe {
            GetLastError()
        }));
    }
    Ok(PathBuf::from(String::from_utf16_lossy(
        &buffer[..capacity as usize],
    )))
}

fn inject(process: HANDLE, dll: &Path) -> Result<(), String> {
    let encoded = wide(dll.as_os_str());
    let bytes = encoded.len() * std::mem::size_of::<u16>();
    let remote = unsafe {
        VirtualAllocEx(
            process,
            null(),
            bytes,
            MEM_COMMIT | MEM_RESERVE,
            PAGE_READWRITE,
        )
    };
    if remote.is_null() {
        return Err(format!("VirtualAllocEx failed: {}", unsafe {
            GetLastError()
        }));
    }
    let mut written = 0usize;
    let write_ok = unsafe {
        windows_sys::Win32::System::Diagnostics::Debug::WriteProcessMemory(
            process,
            remote,
            encoded.as_ptr() as *const c_void,
            bytes,
            &mut written,
        )
    };
    if write_ok == 0 || written != bytes {
        unsafe {
            VirtualFreeEx(process, remote, 0, MEM_RELEASE);
        }
        return Err(format!("WriteProcessMemory failed: {}", unsafe {
            GetLastError()
        }));
    }
    let kernel = unsafe { GetModuleHandleW(wide("kernel32.dll").as_ptr()) };
    if kernel.is_null() {
        unsafe {
            VirtualFreeEx(process, remote, 0, MEM_RELEASE);
        }
        return Err("kernel32.dll is not loaded in the controller".to_string());
    }
    let load_library = unsafe { GetProcAddress(kernel, b"LoadLibraryW\0".as_ptr()) };
    let Some(load_library) = load_library else {
        unsafe {
            VirtualFreeEx(process, remote, 0, MEM_RELEASE);
        }
        return Err("LoadLibraryW is unavailable".to_string());
    };
    let thread = unsafe {
        CreateRemoteThread(
            process,
            null(),
            0,
            Some(std::mem::transmute(load_library)),
            remote,
            0,
            null_mut(),
        )
    };
    if thread.is_null() {
        unsafe {
            VirtualFreeEx(process, remote, 0, MEM_RELEASE);
        }
        return Err(format!("CreateRemoteThread failed: {}", unsafe {
            GetLastError()
        }));
    }
    let wait = unsafe { WaitForSingleObject(thread, 15000) };
    let mut exit_code = 0u32;
    let _ = unsafe { GetExitCodeThread(thread, &mut exit_code) };
    unsafe {
        CloseHandle(thread);
        VirtualFreeEx(process, remote, 0, MEM_RELEASE);
    }
    if wait != WAIT_OBJECT_0 || exit_code == 0 {
        return Err(format!(
            "LoadLibraryW did not complete successfully (wait={wait}, module={exit_code:#x})"
        ));
    }
    Ok(())
}

fn open_pipe(name: &str, timeout: Duration) -> Result<HANDLE, String> {
    let deadline = Instant::now() + timeout;
    let encoded = wide(name);
    loop {
        let pipe = unsafe {
            CreateFileW(
                encoded.as_ptr(),
                FILE_GENERIC_READ | FILE_GENERIC_WRITE,
                0,
                null(),
                OPEN_EXISTING,
                FILE_ATTRIBUTE_NORMAL,
                null_mut(),
            )
        };
        if pipe != INVALID_HANDLE_VALUE {
            return Ok(pipe);
        }
        if Instant::now() >= deadline {
            return Err(format!("named pipe unavailable: {}", unsafe {
                GetLastError()
            }));
        }
        unsafe {
            WaitNamedPipeW(encoded.as_ptr(), NMPWAIT_WAIT_FOREVER);
        }
        thread::sleep(Duration::from_millis(20));
    }
}

fn pipe_request(pipe: HANDLE, command: &str) -> Result<String, String> {
    let payload = format!("{command}\n");
    let bytes = payload.as_bytes();
    let mut written = 0u32;
    let ok = unsafe {
        WriteFile(
            pipe,
            bytes.as_ptr(),
            bytes.len() as u32,
            &mut written,
            null_mut(),
        )
    };
    if ok == 0 {
        return Err(format!("pipe write failed: {}", unsafe { GetLastError() }));
    }
    let mut buffer = [0u8; 4096];
    let mut read = 0u32;
    let ok = unsafe {
        ReadFile(
            pipe,
            buffer.as_mut_ptr(),
            buffer.len() as u32,
            &mut read,
            null_mut(),
        )
    };
    if ok == 0 {
        return Err(format!("pipe read failed: {}", unsafe { GetLastError() }));
    }
    Ok(String::from_utf8_lossy(&buffer[..read as usize])
        .trim()
        .to_string())
}

fn run(args: &[String]) -> Result<(), String> {
    if args.len() < 2 || args[1] != "inject" || !has_arg(args, "--ack-debug-process") {
        usage();
    }
    let pid: u32 = arg_value(args, "--pid")
        .ok_or("--pid is required")?
        .parse()
        .map_err(|_| "invalid --pid")?;
    let dll = PathBuf::from(arg_value(args, "--dll").ok_or("--dll is required")?);
    let profile_path = PathBuf::from(arg_value(args, "--profile").ok_or("--profile is required")?);
    let timeout = arg_value(args, "--timeout-ms")
        .unwrap_or_else(|| "10000".to_string())
        .parse::<u64>()
        .map_err(|_| "invalid --timeout-ms")?;
    let profile = parse_profile(
        &fs::read_to_string(&profile_path).map_err(|err| format!("profile read failed: {err}"))?,
    )?;
    if profile.schema_version != 1 || profile.hook_enabled {
        return Err("profile must be schema 1 with hook_enabled=false until the current signature is verified".to_string());
    }
    if !dll.is_file() {
        return Err(format!("agent DLL does not exist: {}", dll.display()));
    }
    let access = PROCESS_CREATE_THREAD
        | PROCESS_QUERY_LIMITED_INFORMATION
        | PROCESS_VM_OPERATION
        | PROCESS_VM_READ
        | PROCESS_VM_WRITE;
    let process = unsafe { OpenProcess(access, 0, pid) };
    if process.is_null() {
        return Err(format!("OpenProcess failed: {}", unsafe { GetLastError() }));
    }
    let result = (|| {
        let image = query_image_path(process)?;
        let file_name = image
            .file_name()
            .and_then(|name| name.to_str())
            .unwrap_or_default();
        if !file_name.eq_ignore_ascii_case(&profile.executable_name) {
            return Err(format!("target executable mismatch: {file_name}"));
        }
        let actual_hash = sha256(&image)?;
        if !actual_hash.eq_ignore_ascii_case(&profile.sha256) {
            return Err(format!("target SHA-256 mismatch: {actual_hash}"));
        }
        inject(process, &dll)?;
        let name = pipe_name(pid);
        let pipe = open_pipe(&name, Duration::from_millis(timeout))?;
        let hello = pipe_request(pipe, "HELLO")?;
        if !hello.contains(PROTOCOL) || !hello.contains("\"hook_enabled\":false") {
            unsafe {
                CloseHandle(pipe);
            }
            return Err(format!("agent handshake rejected: {hello}"));
        }
        let status = pipe_request(pipe, "STATUS")?;
        let trace_arm = if has_arg(args, "--arm-trace") {
            Some(pipe_request(pipe, "TRACE_ARM")?)
        } else {
            None
        };
        let trace_test = if has_arg(args, "--test-break") || has_arg(args, "--test-int3") {
            if trace_arm.is_none() {
                return Err("--test-break/--test-int3 requires --arm-trace".to_string());
            }
            let command = if has_arg(args, "--test-int3") {
                "TRACE_TEST_INT3"
            } else {
                "TRACE_TEST_BREAK"
            };
            Some(pipe_request(pipe, command)?)
        } else {
            None
        };
        let hold_trace_ms = arg_value(args, "--hold-trace-ms")
            .unwrap_or_else(|| "0".to_string())
            .parse::<u64>()
            .map_err(|_| "invalid --hold-trace-ms")?;
        if hold_trace_ms > 0 {
            if trace_arm.is_none() {
                return Err("--hold-trace-ms requires --arm-trace".to_string());
            }
            thread::sleep(Duration::from_millis(hold_trace_ms));
        }
        let trace_status = if trace_arm.is_some() {
            Some(pipe_request(pipe, "TRACE_STATUS")?)
        } else {
            None
        };
        let shutdown = pipe_request(pipe, "SHUTDOWN")?;
        unsafe {
            CloseHandle(pipe);
        }
        println!("{{\"pid\":{pid},\"image\":{},\"sha256\":{},\"hello\":{},\"status\":{},\"trace_arm\":{},\"trace_test\":{},\"hold_trace_ms\":{hold_trace_ms},\"trace_status\":{},\"shutdown\":{}}}",
            json_quote(&image.display().to_string()), json_quote(&actual_hash), json_quote(&hello), json_quote(&status),
            trace_arm.as_deref().map(json_quote).unwrap_or_else(|| "null".to_string()),
            trace_test.as_deref().map(json_quote).unwrap_or_else(|| "null".to_string()),
            trace_status.as_deref().map(json_quote).unwrap_or_else(|| "null".to_string()),
            json_quote(&shutdown));
        Ok(())
    })();
    unsafe {
        CloseHandle(process);
    }
    result
}

fn main() {
    let args: Vec<String> = env::args().collect();
    if let Err(error) = run(&args) {
        eprintln!("gsvm-controller: {error}");
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::pipe_name;

    #[test]
    fn pipe_names_are_pid_scoped() {
        assert_eq!(pipe_name(42), r"\\.\pipe\sc2-gsvm-agent-42");
    }
}
