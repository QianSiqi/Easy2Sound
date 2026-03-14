import sys, os
import librosa
import numpy as np
import soundfile as sf

filename=""
resampler=""
wavtool=""
singer=""
phonemer=""
tempo=0
blocks=[]
def get_audio_duration_librosa(file_path):
    y, sr = librosa.load(file_path)
    duration = librosa.get_duration(y=y, sr=sr)
    return duration
def create_silence(duration, sr=44100):
    n_samples = int(duration * sr)
    silence = np.zeros(n_samples, dtype=np.float32)
    return silence, sr
def ticks_to_milliseconds(ticks, ticks_per_beat=480, bpm=120):
    # 计算每拍的时间（毫秒）
    beat_duration_ms = 60 * 1000 / bpm  # 一分钟有60秒=60000毫秒
    
    # 计算 ticks 对应的拍数
    beats = ticks / ticks_per_beat
    
    # 计算总毫秒数
    milliseconds = beats * beat_duration_ms
    
    return milliseconds
def read_e2s(filename):
    global resampler,wavtool,singer,phonemer,tempo                                                                                                                                            
    e2s=open(filename,'r',encoding='utf-8').readlines()
    note_mode=False
    blocks=[]
    current_block_idx=-1
    for line in e2s:
        if line.startswith("resampler") :
            resampler=line.split("=")[1].strip()
            continue
        if line.startswith("wavtool") :
            wavtool=line.split("=")[1].strip()
            continue
        if line.startswith("singer") :
            singer=line.split("=")[1].strip()
            continue
        if line.startswith("tempo") and not note_mode:
            tempo=line.split("=")[1].strip()
            continue
        if line.startswith("phonemer") :
            #print(line)
            phonemer=line.split("=")[1].strip()
            print(phonemer+' '+filename+'\n')
            os.system(phonemer+' '+filename)
            #
            # print(phonemer)
            continue
        if line.strip().endswith(":"):
            note_mode=True
            blocks.append([])  # Add a new block list
            current_block_idx += 1  # Increment to point to the new block
            continue
        if note_mode:
            blocks[current_block_idx].append(line.split("=")[1].strip())
            if line.startswith("pitch_string"):
                note_mode=False
    
    return blocks



def call_resampler():
    print("----------------------------")
    global singer,resampler,blocks
    cnt=0
    for block in blocks:
        
        if block[1] == 'sil':
            durations=ticks_to_milliseconds(int(block[6]),480,int(block[9]))
            rate=44100
            print(f"Creating silence of duration {durations} milliseconds at {rate} Hz")
            sil,sr=create_silence(float(durations)/1000)
            file_name=f"tmp/sil_{cnt}.wav"
            sf.write(file_name, sil, sr)
            print('Made silence: '+file_name)
        
        
        else:
            cons=''
            meta=open(singer+'/meta.txt','r',encoding='utf-8').readlines()
            for line in meta:
                if line.startswith(block[1]):  # Using first element as the identifier
                    cons=line.split(',')[2]
            cutoff=get_audio_duration_librosa(singer+'/'+block[1]+'.wav')
            command=f"{resampler} {singer+'/'+block[1]+'.wav'} {'tmp/'+block[1]+'_'+str(cnt)+'.wav'} {block[3]} {block[4]} {block[5]} 0  {int(ticks_to_milliseconds(int(block[6]),480,int(block[9])))} {cons} {cutoff} {block[7]} {block[8]} !{block[9]} {block[10]}"
            print(command+'\n')
            os.system(command)
        cnt+=1

cnt=0
def call_wavtool():
    global wavtool, blocks,cnt
    wavs=[]
    for block in blocks:
        wavs.append('tmp/'+block[1]+'_'+str(cnt)+'.wav')
        cnt+=1
    wavs.append('tmp/out.wav')
    for block in blocks: 
        wavs.append(block[2])
    command=f"{wavtool} {' '.join(wavs)}"
    print(command+'\n')
    os.system(command)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: read_e2s <filename>")
        sys.exit(1)
    filename = sys.argv[1]
    
    # First, read the e2s file to populate global variables
    print("----------------------------")
    print(f"Reading e2s file: {filename}")  
    blocks = read_e2s(filename)
    blocks = read_e2s(filename)
    # Now phonemer variable should be populated
    print(blocks)
    
    os.system('mkdir tmp')
    call_resampler()
    call_wavtool()