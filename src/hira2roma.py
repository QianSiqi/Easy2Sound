import sys
import os

def hira2roma(file_name,dict):
    f=open(dict,'r',encoding='utf-8')
    for lines in f:
        line=lines.strip().split(",")
        if file_name[0]=='_':
            file_name=file_name[1:]
        if line[0]==file_name:
            return line[1]
        
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
            output_file_path = output_dir + "/" + result + ".wav"
            os.system(f"cp {file_dir}/{file_name} {output_file_path}")
            print(f"Copied {file_name} to {output_file_path}")
    
    
    