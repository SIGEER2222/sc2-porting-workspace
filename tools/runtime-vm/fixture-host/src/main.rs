use std::env;
use std::thread;
use std::time::Duration;

fn main() {
    let seconds = env::args().nth(1).and_then(|value| value.parse::<u64>().ok()).unwrap_or(30);
    println!("gsvm-fixture-host pid={} seconds={seconds}", std::process::id());
    thread::sleep(Duration::from_secs(seconds));
}
