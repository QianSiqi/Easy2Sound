// Stub implementation for OpenJTalk FFI symbols
// Required by voirs-g2p crate even when using English-only G2P

int OpenJTalk_initialize(void) { return 0; }
int OpenJTalk_clear(void) { return 0; }
int OpenJTalk_load_voice(const char* voice_path) { return 0; }
int OpenJTalk_synthesis(const char* text, const char* output_wav, const char* output_label) { return 0; }
const char* OpenJTalk_get_phoneme_sequence(const char* text) { return 0; }
void OpenJTalk_free_string(const char* ptr) { }
