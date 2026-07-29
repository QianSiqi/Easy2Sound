import sys
import os
import shutil

def hira2roma(file_name,dict):
    if file_name[0]=='_':
        file_name=file_name[1:]

    # Load dictionary: hiragana -> romanization
    mapping = {}
    with open(dict,'r',encoding='utf-8') as f:
        for lines in f:
            line=lines.strip().split(",")
            if len(line)==2 and line[0] and line[1]:
                mapping[line[0]]=line[1]

    # Sort keys by length descending for greedy longest-match
    sorted_keys=sorted(mapping.keys(),key=len,reverse=True)

    # If filename is 1 character, try whole match
    if len(file_name)==1:
        return mapping.get(file_name)

    # Multi-character: convert each hiragana individually
    result=""
    i=0
    while i<len(file_name):
        matched=False
        for key in sorted_keys:
            if file_name[i:].startswith(key):
                result+=mapping[key]
                i+=len(key)
                matched=True
                break
        if not matched:
            # If it's a hiragana char with no match, skip this file
            if '\u3040'<=file_name[i]<='\u309f':
                return None
            i+=1
    return result if result else None
        
if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python hira2roma.py <file_dir> <dict> <output_dir>")
        sys.exit(1)

    file_dir = sys.argv[1]
    dict_file = sys.argv[2]
    output_dir = sys.argv[3]

    file_names = os.listdir(file_dir)
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    for file_name in file_names:
        file_path = file_name.split(".")[0]
        result = hira2roma(file_path, dict_file)
        print(f"{file_path} -> {result}")
        if result is not None:
            src = os.path.join(file_dir, file_name)
            dst = os.path.join(output_dir, result + ".wav")
            shutil.copy(src, dst)
            print(f"Copied {file_name} to {dst}")
    
    
    