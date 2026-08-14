// 轻量日志：带时间戳的控制台输出，与 python 版 logging 风格一致
use std::time::{SystemTime, UNIX_EPOCH};

fn now_ts() -> String {
    let d = SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default();
    let h = d.as_secs() / 3600 % 24;
    let m = d.as_secs() / 60 % 60;
    let s = d.as_secs() % 60;
    format!("{h:02}:{m:02}:{s:02}.{:03}", d.subsec_millis())
}

pub fn info(msg: &str) {
    println!("[{}] {}", now_ts(), msg);
}

pub fn warn(msg: &str) {
    println!("[{}] WARN {}", now_ts(), msg);
}

pub fn error(msg: &str) {
    eprintln!("[{}] ERROR {}", now_ts(), msg);
}
