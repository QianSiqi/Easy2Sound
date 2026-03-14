import sys
import os
import librosa
import soundfile as sf
import numpy as np

current_blocks = []

def read_mue2s(filename):
    """Parse the .mue2s file to extract file and volume information for each track"""
    global current_blocks
    current_blocks = []  # Reset blocks list
    
    with open(filename, 'r', encoding='utf-8') as mue2s:
        lines = mue2s.readlines()
    
    track_mode = False
    current_track = {}
    
    for line in lines:
        line = line.strip()
        if line.endswith(':'):
            # If we were processing a previous track, save it
            if track_mode and 'file' in current_track and 'volume' in current_track:
                current_blocks.append(current_track.copy())
            
            # Start a new track
            track_mode = True
            current_track = {}
            continue
        
        if track_mode and '=' in line:
            # Parse parameter
            key, value = line.split('=', 1)  # Split only on first '=' in case value contains '='
            key = key.strip()
            value = value.strip()
            
            if key == 'file':
                current_track['file'] = value
            elif key == 'volume':
                current_track['volume'] = float(value)
    
    # Don't forget the last track
    if track_mode and 'file' in current_track and 'volume' in current_track:
        current_blocks.append(current_track)


def call_read_e2s(output_name):
    """Process each track: call read_e2s, rename files, adjust volume, and stack audios"""
    global current_blocks
    
    # Step 1: Generate individual tracks by calling read_e2s
    for i in range(len(current_blocks)):
        input_file = current_blocks[i]['file']
        command = f"python read_e2s.py {input_file}"
        print(f"Processing track {i+1}: {command}")
        os.system(command)
        
        # Move the output file to track{i}.wav
        os.rename('tmp/out.wav', f'tmp/track{i}.wav')
        
        # Step 2: Adjust volume gain (in dB) for this track
        volume_db = current_blocks[i]['volume']
        
        # Load the audio
        audio, sr = librosa.load(f'tmp/track{i}.wav', sr=44100)
        
        # Calculate scale factor from dB
        scale_factor = 10 ** (volume_db / 20.0)
        
        # Apply volume adjustment
        adjusted_audio = audio * scale_factor
        
        # Clip to prevent overflow
        adjusted_audio = np.clip(adjusted_audio, -1.0, 1.0)
        
        # Save the adjusted audio back
        sf.write(f'tmp/track{i}.wav', adjusted_audio, sr)
        print(f"Adjusted volume for track{i}.wav (gain: {volume_db} dB)")
    
    # Step 3: Stack all track{i}.wav files together
    print("Stacking all tracks together...")
    stacked_audio = None
    sample_rate = None
    
    for i in range(len(current_blocks)):
        # Load the adjusted track
        track_audio, track_sr = librosa.load(f'tmp/track{i}.wav', sr=44100)
        
        if sample_rate is None:
            sample_rate = track_sr
        
        if stacked_audio is None:
            # Initialize with the first track
            stacked_audio = track_audio
        else:
            # Handle different lengths by padding the shorter one
            max_len = max(len(stacked_audio), len(track_audio))
            
            # Pad both arrays to the same length
            if len(stacked_audio) < max_len:
                padded_stacked = np.zeros(max_len)
                padded_stacked[:len(stacked_audio)] = stacked_audio
                stacked_audio = padded_stacked
            
            if len(track_audio) < max_len:
                padded_track = np.zeros(max_len)
                padded_track[:len(track_audio)] = track_audio
                track_audio = padded_track
            
            # Add the current track to the stacked audio
            stacked_audio = stacked_audio + track_audio
    
    # Normalize to prevent clipping after stacking
    max_amplitude = np.max(np.abs(stacked_audio))
    if max_amplitude > 1.0:
        print(f"Normalizing output to prevent clipping (max amplitude was {max_amplitude:.3f})")
        stacked_audio = stacked_audio / max_amplitude
    
    # Step 4: Save the final stacked audio
    output_path = f'tmp/{output_name}.wav'
    sf.write(output_path, stacked_audio, sample_rate)
    print(f"All tracks stacked and saved as {output_path}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python read_mue2s.py <input.mue2s> <output_name>")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_name = sys.argv[2]
    
    # Parse the .mue2s file
    read_mue2s(input_file)
    
    # Process and stack the tracks
    call_read_e2s(output_name)