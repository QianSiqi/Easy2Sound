use std::env;
use std::fs::read_to_string;
use pinyin::ToPinyin; // 启用 to_pinyin 方法

// 汉字转拼音（每个汉字转为无声调小写拼音，空格分隔）
fn chinese_to_pinyin(text: &str) -> String {
    let mut parts = Vec::new();
    for ch in text.chars() {
        if let Some(p) = ch.to_pinyin() {
            // p.plain() 返回无声调的小写拼音字符串
            parts.push(p.plain().to_string());
        } else {
            // 非汉字字符原样保留
            parts.push(ch.to_string());
        }
    }
    parts.join(" ")
}

// 将空格分隔的字符串转换为逗号分隔
fn space_to_comma_separated(phoneme_str: &str) -> String {
    let phonemes: Vec<&str> = phoneme_str.split_whitespace().collect();
    phonemes.join(",")
}

// 处理单个音符块
fn process_note_block(block: &str) -> String {
    let mut result = String::new();
    let mut lines = block.lines();

    // 第一行是音符编号（如 "1:"）
    if let Some(note_header) = lines.next() {
        result.push_str(note_header);
        result.push('\n');
    }

    // 预先提取 lyric 值
    let mut lyric = String::new();
    for line in block.lines() {
        if line.starts_with("lyric=") {
            if let Some(val) = line.strip_prefix("lyric=") {
                lyric = val.trim().to_string();
                break;
            }
        }
    }

    // 处理每一行
    for line in lines {
        if line.starts_with("lyric=") {
            result.push_str(line);
            result.push('\n');
        } else if line.starts_with("phoneme=") {
            if !lyric.is_empty() {
                let pinyin_str = chinese_to_pinyin(&lyric);
                let comma_separated = space_to_comma_separated(&pinyin_str);
                result.push_str(&format!("phoneme={}", comma_separated));
            } else {
                result.push_str("phoneme=");
            }
            result.push('\n');
        } else {
            result.push_str(line);
            result.push('\n');
        }
    }

    result
}

// 处理整个文件
fn process_temp_file(file_content: &str) -> String {
    let lines: Vec<&str> = file_content.lines().collect();
    let mut result = String::new();
    let mut current_block = String::new();
    let mut in_note_section = false;

    for line in lines {
        if line.chars().next().map_or(false, |c| c.is_ascii_digit()) && line.contains(':') {
            if !current_block.is_empty() {
                if in_note_section {
                    result.push_str(&process_note_block(&current_block));
                } else {
                    result.push_str(&current_block);
                }
            }
            current_block.clear();
            current_block.push_str(line);
            current_block.push('\n');
            in_note_section = true;
        } else {
            current_block.push_str(line);
            current_block.push('\n');
        }
    }

    if !current_block.is_empty() {
        if in_note_section {
            result.push_str(&process_note_block(&current_block));
        } else {
            result.push_str(&current_block);
        }
    }

    result
}

fn main() {
    let args: Vec<String> = env::args().collect();

    if args.len() < 2 {
        eprintln!("Usage: {} <temp.e2s_file_path>", args[0]);
        std::process::exit(1);
    }

    let file_path = &args[1];

    let file_content = match read_to_string(file_path) {
        Ok(content) => content,
        Err(e) => {
            eprintln!("Error reading file: {}", e);
            std::process::exit(1);
        }
    };

    let processed_content = process_temp_file(&file_content);

    match std::fs::write(file_path, processed_content) {
        Ok(_) => {
            println!("File processed successfully with pinyin (plain, lowercase)!");
        }
        Err(e) => {
            eprintln!("Error writing file: {}", e);
            std::process::exit(1);
        }
    }
}