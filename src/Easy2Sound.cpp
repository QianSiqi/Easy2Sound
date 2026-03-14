#include <windows.h>
#include <string>
#include <fstream>
#include <vector>
#include <sstream>
using namespace std;
vector<string> missing;
vector<string> missing_instrument_files;
vector<string> missing_music_files;
string python_cmd = "python";
bool FileExists(string f) { 
    DWORD a = GetFileAttributesA(f.c_str()); 
    return (a != INVALID_FILE_ATTRIBUTES && !(a & FILE_ATTRIBUTE_DIRECTORY)); 
}
bool FolderExists(string f) { 
    DWORD a = GetFileAttributesA(f.c_str()); 
    return (a != INVALID_FILE_ATTRIBUTES && (a & FILE_ATTRIBUTE_DIRECTORY)); 
}
bool FindPython() {
    if (FileExists("Main-Run\\RunTime\\python.exe")) { 
        python_cmd = "Main-Run\\RunTime\\python.exe"; 
        return true; 
    }
    HKEY h; 
    if (RegOpenKeyExA(HKEY_LOCAL_MACHINE, "SOFTWARE\\Python\\PythonCore", 0, KEY_READ, &h) == ERROR_SUCCESS) { 
        RegCloseKey(h); 
        python_cmd = "python"; 
        return true; 
    }
    const char* ps[] = {
    	"Main-Run\\RunTime\\python.exe",
        "C:\\Python39\\python.exe",
        "C:\\Python310\\python.exe",
        "C:\\Python311\\python.exe",
        "C:\\Python312\\python.exe",
        "C:\\Python38\\python.exe",
        "C:\\Python37\\python.exe"
    };
    for (const char* p : ps) 
        if (FileExists(p)) { 
            python_cmd = p; 
            return true; 
        }
    return false;
}
void ShowError(string m) { 
    MessageBoxA(NULL, m.c_str(), "Error", MB_OK | MB_ICONERROR); 
} 
void ParseMusicLine(const string& line, string& subfolder, string& filename) {
    size_t pos = line.find("//");
    if (pos != string::npos) {
        subfolder = line.substr(0, pos);
        filename = line.substr(pos + 2);
        if (!subfolder.empty() && subfolder.back() == ' ') subfolder.pop_back();
        if (!filename.empty() && filename.front() == ' ') filename.erase(0, 1);
    }
}
int WINAPI WinMain(HINSTANCE h,HINSTANCE p,LPSTR c,int s) {
    HWND con = GetConsoleWindow(); 
    if (con) ShowWindow(con, SW_HIDE);
    if (!FindPython()) { 
        ShowError("Python not found(缺失运行环境python)"); 
        return 1; 
    }
    if (!FolderExists("Main-Run")) { 
        ShowError("Main-Run folder not found(文件夹未发现)"); 
        return 1; 
    }
    if (!FolderExists("Self-test")) { 
        ShowError("Self-test folder not found(文件夹未发现)"); 
        return 1; 
    }
    if (!FolderExists("LOOK_ME!!!")) { 
        ShowError("LOOK_ME!!! folder not found(文件夹未发现)"); 
        return 1; 
    }
    if (!FileExists("LOOK_ME!!!\\LOOK_ME!!!.md")) {
        ShowError("LOOK_ME!!!.md not found in LOOK_ME!!! folder(LOOK_ME!!!.md未发现于LOOK_ME!!!)");
        return 1;
    }
    
    if (!FileExists("LOOK_ME!!!\\LOOK_ME!!!.txt")) {
        ShowError("LOOK_ME!!!.txt not found in LOOK_ME!!! folder(LOOK_ME!!!.txt未发现于LOOK_ME!!!)");
        return 1;
    }
    string music_line;
    vector<string> instrument_subfolders;
    vector<string> audio_files;
    ifstream f("Self-test\\Test-data.txt");
    if (!f.is_open()) { 
        ShowError("Cannot open Test-data.txt(Test-data.txt未发现于Self-test)"); 
        return 1; 
    }
    string line;
    while (getline(f, line)) {
        if (!line.empty() && line.back() == '\r') line.pop_back();
        if (line.empty()) continue;
        if (!FileExists("Main-Run\\"+line)) {
            missing.push_back(line);
        }
    }
    f.close();
    if (!missing.empty()) {
        string msg = "Missing files in Main-Run(Main-Run文件缺失):\n";
        for (auto& x:missing) msg += x + "\n";
        ShowError(msg); 
        return 1;
    }
    if (!FileExists("Main-Run\\open.py")) {
        ShowError("open.py not found in Main-Run(open.py未发现于Main-Run)");
        return 1;
    }
    string cmd = python_cmd + " Main-Run\\open.py";
    WinExec(cmd.c_str(), SW_SHOW);
    return 0;
}
