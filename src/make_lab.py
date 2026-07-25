import os
import sys

def make_lab(file_name,file_dir):
    lab=open(file_dir+'/'+file_name+'.lab','w',encoding='utf-8')
    phonemes=file_name.split('_')
    for phoneme in phonemes:
        lab.write(phoneme+' ')

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python make_lab.py <file_dir> <output_dir>")
        sys.exit(1)

    file_dir = sys.argv[1]
    output_dir = sys.argv[2]

    file_names = os.listdir(file_dir)
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    for file_name in file_names:
        file_path = file_name.split(".")[0]
        make_lab(file_path, output_dir)
        print(f"Created {file_path}.lab in {output_dir}")