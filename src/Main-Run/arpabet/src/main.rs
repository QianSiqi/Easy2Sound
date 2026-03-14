use std::collections::HashMap;
use std::env;
use std::fs::{File, read_to_string};
use std::io::{BufRead, BufReader, Write};

fn get_base_word(s: &str) -> String {
    if let Some(pos) = s.find('(') {
        s[..pos].trim().to_string()
    } else {
        s.trim().to_string()
    }
    .to_uppercase()
}

fn load_dictionary_from_text(file_path: &str) -> Result<HashMap<String, Vec<String>>, Box<dyn std::error::Error>> {
    let file = File::open(file_path)?;
    let reader = BufReader::new(file);
    let mut dict = HashMap::new();

    for line in reader.lines() {
        let line = line?;
        let line = line.trim();
        if line.is_empty() || line.starts_with("#") {
            continue;
        }

        // Skip lines that start with non-alphabetic characters (like punctuation marks)
        if let Some(first_char) = line.chars().next() {
            if !first_char.is_alphabetic() {
                continue;
            }
        }

        if let Some((w, pron)) = line.split_once(char::is_whitespace) {
            let base_word = get_base_word(w);
            let pron = pron.trim().to_string();
            dict.entry(base_word)
                .or_insert_with(Vec::new)
                .push(pron);
        }
    }
    
    Ok(dict)
}

// 将空格分隔的音素转换为逗号分隔
fn space_to_comma_separated(phoneme_str: &str) -> String {
    let phonemes: Vec<&str> = phoneme_str.split_whitespace().collect();
    phonemes.join(",")
}

// 解析音符块并查找音素
fn process_note_block(block: &str, dict: &HashMap<String, Vec<String>>) -> String {
    let mut result = String::new();
    let mut lines = block.lines();
    
    // 第一行是音符编号
    if let Some(note_header) = lines.next() {
        result.push_str(note_header);
        result.push('\n');
    }
    
    // 处理lyric和phoneme行
    for line in lines {
        if line.starts_with("lyric=") {
            result.push_str(line);
            result.push('\n');
        } else if line.starts_with("phoneme=") {
            // 提取lyric的值来查找音素
            let lyric_line = block.lines().find(|l| l.starts_with("lyric="));
            if let Some(lyric_line) = lyric_line {
                let lyric = lyric_line.strip_prefix("lyric=").unwrap_or("").trim();
                if !lyric.is_empty() && lyric != "" {
                    let base_word = get_base_word(lyric);
                    if let Some(prons) = dict.get(&base_word) {
                        // 使用第一个找到的发音，并将空格分隔转换为逗号分隔
                        let comma_separated = space_to_comma_separated(&prons[0]);
                        result.push_str(&format!("phoneme={}", comma_separated));
                    } else {
                        // 如果找不到音素，直接填入lyric本身
                        result.push_str(&format!("phoneme={}", lyric));
                    }
                } else {
                    result.push_str("phoneme=");
                }
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

// 处理整个temp.e2s文件
fn process_temp_file(file_content: &str, dict: &HashMap<String, Vec<String>>) -> String {
    let lines: Vec<&str> = file_content.lines().collect();
    let mut result = String::new();
    let mut current_block = String::new();
    let mut in_note_section = false;
    
    for line in lines {
        // 检查是否是音符块的开始（以数字:开头的行）
        if line.chars().next().map_or(false, |c| c.is_digit(10)) && line.contains(':') {
            // 如果之前有积压的块，先处理它
            if !current_block.is_empty() {
                if in_note_section {
                    // 如果在音符区域，处理当前音符块
                    result.push_str(&process_note_block(&current_block, dict));
                } else {
                    // 如果不在音符区域，直接添加（这是配置部分）
                    result.push_str(&current_block);
                }
            }
            // 开始新的音符块
            current_block.clear();
            current_block.push_str(line);
            current_block.push('\n');
            in_note_section = true;
        } else {
            // 不是以数字:开头的行
            current_block.push_str(line);
            current_block.push('\n');
        }
    }
    
    // 处理最后一个块
    if !current_block.is_empty() {
        if in_note_section {
            result.push_str(&process_note_block(&current_block, dict));
        } else {
            result.push_str(&current_block);
        }
    }
    
    result
}

fn main() {
    let args: Vec<String> = env::args().collect();
    
    // 需要一个参数（temp.e2s文件路径）
    if args.len() < 2 {
        eprintln!("Usage: {} <temp.e2s_file_path>", args[0]);
        std::process::exit(1);
    }

    let file_path = &args[1];
    let dict_path = if args.len() > 2 { &args[2] } else { "cmudict_SPHINX_40.txt" };

    // 加载字典
    let dict = match load_dictionary_from_text(dict_path) {
        Ok(d) => d,
        Err(e) => {
            eprintln!("Error loading dictionary: {}", e);
            std::process::exit(1);
        }
    };

    // 读取temp.e2s文件
    let file_content = match read_to_string(file_path) {
        Ok(content) => content,
        Err(e) => {
            eprintln!("Error reading file: {}", e);
            std::process::exit(1);
        }
    };

    // 处理文件内容
    let processed_content = process_temp_file(&file_content, &dict);

    // 覆盖保存文件
    match std::fs::write(file_path, processed_content) {
        Ok(_) => {
            println!("File processed successfully!");
        }
        Err(e) => {
            eprintln!("Error writing file: {}", e);
            std::process::exit(1);
        }
    }
}