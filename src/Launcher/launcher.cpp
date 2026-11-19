#ifndef UNICODE
#define UNICODE
#endif
#define _UNICODE
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <commctrl.h>
#include <shobjidl.h>
#include <shellapi.h>
#include <bcrypt.h>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <vector>
#include <string>
#include <array>
#include <stdexcept>
#include <algorithm>
#include "vendor/miniz/miniz.h"
namespace fs=std::filesystem;
static HWND window_,label_,bar_,path_,start_,browse_;
static bool cancelled=false,choosing=false,quiet=false;
static HFONT font_=CreateFontW(-15,0,0,0,FW_NORMAL,FALSE,FALSE,FALSE,DEFAULT_CHARSET,OUT_DEFAULT_PRECIS,CLIP_DEFAULT_PRECIS,CLEARTYPE_QUALITY,DEFAULT_PITCH,L"Microsoft YaHei UI");
static HBRUSH background=CreateSolidBrush(RGB(8,14,23));
static const wchar_t* title=L"Sekiro Character Toolkit · 0.10.10";
static std::wstring wide(const std::string& s){int n=MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,s.data(),(int)s.size(),0,0);if(!n&&s.size())throw std::runtime_error("Invalid UTF-8");std::wstring r(n,0);MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,s.data(),(int)s.size(),r.data(),n);return r;}
static std::string utf8(const std::wstring& s){int n=WideCharToMultiByte(CP_UTF8,0,s.data(),(int)s.size(),0,0,0,0);std::string r(n,0);WideCharToMultiByte(CP_UTF8,0,s.data(),(int)s.size(),r.data(),n,0,0);return r;}
static void fail(const std::string& s){throw std::runtime_error(s+" (Windows="+std::to_string(GetLastError())+")");}
struct Handle{HANDLE h=INVALID_HANDLE_VALUE;Handle()=default;explicit Handle(HANDLE v):h(v){}~Handle(){if(h!=INVALID_HANDLE_VALUE&&h)CloseHandle(h);}Handle(const Handle&)=delete;Handle& operator=(const Handle&)=delete;};
static void pump(){MSG m;while(PeekMessageW(&m,0,0,0,PM_REMOVE)){if(m.message==WM_QUIT)cancelled=true;TranslateMessage(&m);DispatchMessageW(&m);}if(cancelled)throw std::runtime_error("Cancelled / 已取消；可再次运行继续准备");}
static void progress(const std::wstring& s,int percent){if(!quiet){SetWindowTextW(label_,s.c_str());SendMessageW(bar_,PBM_SETPOS,percent,0);pump();}}
static fs::path chooseFolder(){IFileOpenDialog* d=nullptr;fs::path p;if(SUCCEEDED(CoCreateInstance(CLSID_FileOpenDialog,0,CLSCTX_INPROC_SERVER,IID_PPV_ARGS(&d)))){DWORD f;d->GetOptions(&f);d->SetOptions(f|FOS_PICKFOLDERS|FOS_FORCEFILESYSTEM);d->SetTitle(L"选择工具数据存放目录（工具链、缓存和导出默认均放在这里）");if(SUCCEEDED(d->Show(window_))){IShellItem* item=nullptr;if(SUCCEEDED(d->GetResult(&item))){PWSTR name=nullptr;if(SUCCEEDED(item->GetDisplayName(SIGDN_FILESYSPATH,&name))){p=name;CoTaskMemFree(name);}item->Release();}}d->Release();}return p;}
static LRESULT CALLBACK wndproc(HWND h,UINT m,WPARAM w,LPARAM l){switch(m){case WM_CLOSE:cancelled=true;return 0;case WM_COMMAND:if(LOWORD(w)==101){auto p=chooseFolder();if(!p.empty())SetWindowTextW(path_,p.c_str());}if(LOWORD(w)==102)choosing=false;return 0;case WM_CTLCOLORSTATIC:SetTextColor((HDC)w,RGB(211,234,242));SetBkColor((HDC)w,RGB(8,14,23));return (LRESULT)background;case WM_ERASEBKGND:{RECT r;GetClientRect(h,&r);FillRect((HDC)w,&r,background);return 1;}}return DefWindowProcW(h,m,w,l);}
static void ui(HINSTANCE instance){INITCOMMONCONTROLSEX c{sizeof(c),ICC_PROGRESS_CLASS};InitCommonControlsEx(&c);WNDCLASSW wc{};wc.hInstance=instance;wc.lpfnWndProc=wndproc;wc.lpszClassName=L"SCTPortableLauncher";wc.hbrBackground=background;wc.hCursor=LoadCursor(0,IDC_ARROW);wc.hIcon=LoadIconW(instance,MAKEINTRESOURCEW(1));RegisterClassW(&wc);int x=(GetSystemMetrics(SM_CXSCREEN)-680)/2,y=(GetSystemMetrics(SM_CYSCREEN)-295)/2;window_=CreateWindowW(wc.lpszClassName,title,WS_CAPTION|WS_SYSMENU,x,y,680,295,0,0,instance,0);
 auto control=[&](const wchar_t* cls,const wchar_t* text,DWORD style,int x,int y,int width,int height,int id=0){HWND h=CreateWindowW(cls,text,WS_CHILD|WS_VISIBLE|style,x,y,width,height,window_,(HMENU)(INT_PTR)id,instance,0);SendMessageW(h,WM_SETFONT,(WPARAM)font_,TRUE);return h;};
 control(L"STATIC",L"SEKIRO  /  CHARACTER TOOLKIT",0,24,20,620,24);
 label_=control(L"STATIC",L"内置角色、武器、动作与音频工具链 · 无需安装运行环境",0,24,54,620,40);
 path_=control(L"EDIT",L"",WS_BORDER|ES_AUTOHSCROLL,24,108,515,26);browse_=control(L"BUTTON",L"浏览…",0,548,108,90,26,101);
 bar_=control(PROGRESS_CLASSW,L"",0,24,156,614,12);SendMessageW(bar_,PBM_SETRANGE32,0,100);start_=control(L"BUTTON",L"准备并启动",BS_DEFPUSHBUTTON,478,199,160,32,102);
 control(L"STATIC",L"首次释放到所选目录；之后校验并复用，不写入 C 盘临时目录。",0,24,202,450,40);
 if(!quiet)ShowWindow(window_,SW_SHOW);
}
struct Hash{BCRYPT_ALG_HANDLE alg=nullptr;BCRYPT_HASH_HANDLE h=nullptr;Hash(){if(BCryptOpenAlgorithmProvider(&alg,BCRYPT_SHA256_ALGORITHM,0,0)<0||BCryptCreateHash(alg,&h,0,0,0,0,0)<0)throw std::runtime_error("SHA-256 init failed");}~Hash(){if(h)BCryptDestroyHash(h);if(alg)BCryptCloseAlgorithmProvider(alg,0);}void add(const void* p,size_t n){if(BCryptHashData(h,(PUCHAR)p,(ULONG)n,0)<0)throw std::runtime_error("SHA-256 update failed");}std::string end(){unsigned char digest[32];if(BCryptFinishHash(h,digest,32,0)<0)throw std::runtime_error("SHA-256 finish failed");const char* hex="0123456789abcdef";std::string r;for(auto b:digest){r+=hex[b>>4];r+=hex[b&15];}return r;}};
static void seek(HANDLE h,uint64_t offset){LARGE_INTEGER a;a.QuadPart=offset;if(!SetFilePointerEx(h,a,0,FILE_BEGIN))fail("Seek failed");}
static std::string hashRange(HANDLE h,uint64_t offset,uint64_t size,bool show=false){Hash hash;std::vector<unsigned char>b(1024*1024);seek(h,offset);uint64_t done=0;while(done<size){DWORD n=0,want=(DWORD)std::min<uint64_t>(b.size(),size-done);if(!ReadFile(h,b.data(),want,&n,0)||!n)fail("Read failed");hash.add(b.data(),n);done+=n;if(show&&!(done%(16*1024*1024)))progress(L"正在验证单文件安装包 SHA-256…",(int)(done*100/size));}return hash.end();}
static std::string hashFile(const fs::path& p,uint64_t bytes){Handle h(CreateFileW(p.c_str(),GENERIC_READ,FILE_SHARE_READ,0,OPEN_EXISTING,FILE_FLAG_SEQUENTIAL_SCAN,0));if(h.h==INVALID_HANDLE_VALUE)return "";LARGE_INTEGER s;if(!GetFileSizeEx(h.h,&s)||(uint64_t)s.QuadPart!=bytes)return "";return hashRange(h.h,0,bytes);}
static void safePath(const fs::path& root,const fs::path& rel){if(rel.empty()||rel.is_absolute()||rel.has_root_name())throw std::runtime_error("Unsafe archive path");for(const auto& part:rel)if(part==L".."||part==L"."||part.wstring().find(L':')!=std::wstring::npos)throw std::runtime_error("Unsafe archive path");fs::path current=root;std::vector<fs::path> paths;for(auto p=root;!p.empty();){paths.push_back(p);auto parent=p.parent_path();if(parent==p)break;p=parent;}for(auto part:rel){current/=part;paths.push_back(current);}for(const auto& p:paths){DWORD a=GetFileAttributesW(p.c_str());if(a!=INVALID_FILE_ATTRIBUTES&&(a&FILE_ATTRIBUTE_REPARSE_POINT))throw std::runtime_error("Reparse-point data paths are not supported: "+utf8(p.wstring()));}}
struct Archive{HANDLE h;uint64_t offset;};
static size_t readZip(void* opaque,mz_uint64 off,void* data,size_t n){auto& a=*(Archive*)opaque;LARGE_INTEGER pos;pos.QuadPart=a.offset+off;DWORD got=0;if(!SetFilePointerEx(a.h,pos,0,FILE_BEGIN)||!ReadFile(a.h,data,(DWORD)n,&got,0))return 0;return got;}
static size_t writeZip(void* opaque,mz_uint64, const void* data,size_t n){if(!quiet){MSG m;while(PeekMessageW(&m,0,0,0,PM_REMOVE)){TranslateMessage(&m);DispatchMessageW(&m);}}DWORD done=0;if(cancelled||!WriteFile(*(HANDLE*)opaque,data,(DWORD)n,&done,0))return 0;return done;}
static std::wstring quote(const std::wstring& s){std::wstring r=L"\"";int slashes=0;for(auto c:s){if(c==L'\\'){slashes++;continue;}if(c==L'\"')r.append(slashes*2+1,L'\\');else r.append(slashes,L'\\');slashes=0;r+=c;}r.append(slashes*2,L'\\');return r+L"\"";}
static std::string readText(const fs::path& p){std::ifstream f(p,std::ios::binary);return std::string(std::istreambuf_iterator<char>(f),{});}
static void writeText(const fs::path& p,const std::string& text){std::ofstream f(p,std::ios::binary|std::ios::trunc);if(!f||!f.write(text.data(),text.size()))fail("Cannot write "+utf8(p.wstring()));}
static void env(const wchar_t* key,const fs::path& value){SetEnvironmentVariableW(key,value.c_str());}
int WINAPI wWinMain(HINSTANCE instance,HINSTANCE,LPWSTR,int){fs::path data,app,exe;bool verifyOnly=false;uint32_t repaired=0;int result=1;Handle lock;try{
 CoInitializeEx(0,COINIT_APARTMENTTHREADED);std::vector<wchar_t> module(32768);GetModuleFileNameW(0,module.data(),(DWORD)module.size());exe=module.data();int argc=0;LPWSTR* argv=CommandLineToArgvW(GetCommandLineW(),&argc);std::vector<std::wstring> forward;bool choose=false;
 for(int i=1;i<argc;i++){std::wstring a=argv[i];if(a==L"--data-dir"){if(++i>=argc)throw std::runtime_error("--data-dir needs a directory");data=argv[i];}else if(a==L"--verify-only")verifyOnly=true;else if(a==L"--quiet")quiet=true;else if(a==L"--choose-dir")choose=true;else forward.push_back(a);}LocalFree(argv);
 fs::path prefs=exe; prefs+=L".location";if(data.empty()&&!choose&&fs::exists(prefs)){auto s=readText(prefs);if(!s.empty())data=wide(s);}
 bool mustChoose=data.empty()||choose;if(data.empty())data=exe.parent_path()/L"SekiroCharacterToolkit-data";ui(instance);SetWindowTextW(path_,data.c_str());
 if(mustChoose&&!quiet){choosing=true;progress(L"请选择工具数据目录。建议非 C 盘，至少预留 4 GB；导出模型需额外空间。",0);while(choosing){pump();Sleep(20);}std::vector<wchar_t> b(32768);GetWindowTextW(path_,b.data(),(int)b.size());data=b.data();}
 if(data.empty()||!data.is_absolute())throw std::runtime_error("请选择绝对路径 / Absolute data path required");data=fs::absolute(data).lexically_normal();if(data==data.root_path())throw std::runtime_error("请选择磁盘下的子文件夹，而不是磁盘根目录");if(data.wstring().size()>140)throw std::runtime_error("数据目录过长，请选择少于 140 字符的目录");safePath(data,L"app");fs::create_directories(data);writeText(data/L".write-test","ok");fs::remove(data/L".write-test");
 lock.h=CreateFileW((data/L"launcher.lock").c_str(),GENERIC_READ|GENERIC_WRITE,0,0,OPEN_ALWAYS,FILE_ATTRIBUTE_NORMAL,0);if(lock.h==INVALID_HANDLE_VALUE)throw std::runtime_error("此数据目录已有工具正在运行或准备，请关闭后再试 / Data directory busy");
 EnableWindow(path_,FALSE);EnableWindow(browse_,FALSE);EnableWindow(start_,FALSE);
 Handle source(CreateFileW(exe.c_str(),GENERIC_READ,FILE_SHARE_READ,0,OPEN_EXISTING,FILE_FLAG_SEQUENTIAL_SCAN,0));if(source.h==INVALID_HANDLE_VALUE)fail("Cannot read executable");LARGE_INTEGER size;if(!GetFileSizeEx(source.h,&size)||size.QuadPart<88)fail("Invalid package");std::array<char,88> footer{};seek(source.h,size.QuadPart-footer.size());DWORD n;if(!ReadFile(source.h,footer.data(),footer.size(),&n,0)||n!=footer.size()||memcmp(footer.data(),"SCTPKG02",8))throw std::runtime_error("单文件资源包缺失或损坏 / Invalid package footer");uint64_t offset,length;memcpy(&offset,footer.data()+8,8);memcpy(&length,footer.data()+16,8);if(offset>(uint64_t)size.QuadPart-88||length!=(uint64_t)size.QuadPart-88-offset)throw std::runtime_error("Package bounds invalid");std::string expected(footer.data()+24,64);if(hashRange(source.h,offset,length,true)!=expected)throw std::runtime_error("安装包校验失败，请重新获取完整 EXE / Payload SHA-256 mismatch");
 app=data/L"app"/(L"0.10.10-"+wide(expected.substr(0,12)));safePath(data,fs::relative(app,data));fs::create_directories(app);Archive a{source.h,offset};mz_zip_archive zip{};zip.m_pRead=readZip;zip.m_pIO_opaque=&a;if(!mz_zip_reader_init(&zip,length,0))throw std::runtime_error("ZIP open failed");struct EndZip{mz_zip_archive* z;~EndZip(){mz_zip_reader_end(z);}} endZip{&zip};
 size_t manifestSize=0;char* manifest=(char*)mz_zip_reader_extract_file_to_heap(&zip,"payload.sha256",&manifestSize,0);if(!manifest)throw std::runtime_error("Missing payload manifest");std::string manifestText(manifest,manifestSize);mz_free(manifest);std::istringstream input(manifestText);std::string line;struct Entry{std::string hash,name;uint64_t size;};std::vector<Entry> entries;uint64_t missingBytes=0;
 while(std::getline(input,line)){if(line.empty())continue;auto tab=line.find('\t'),tab2=line.find('\t',tab+1);if(tab!=64||tab2==std::string::npos)throw std::runtime_error("Bad manifest");entries.push_back({line.substr(0,tab),line.substr(tab2+1),std::stoull(line.substr(tab+1,tab2-tab-1))});missingBytes+=entries.back().size;}
 if(entries.size()+1!=zip.m_total_files)throw std::runtime_error("Manifest file count mismatch");std::vector<Entry> repair;
 for(size_t i=0;i<entries.size();i++){const auto& e=entries[i];auto rel=fs::path(wide(e.name));safePath(app,rel);progress(L"校验内置工具链 "+std::to_wstring(i+1)+L" / "+std::to_wstring(entries.size()),(int)((i+1)*100/entries.size()));if(hashFile(app/rel,e.size)!=e.hash)repair.push_back(e);}
 uint64_t needed=128*1024*1024;for(auto& e:repair)needed+=e.size;ULARGE_INTEGER freeBytes;if(!GetDiskFreeSpaceExW(data.c_str(),&freeBytes,0,0)||freeBytes.QuadPart<needed)throw std::runtime_error("所选磁盘空间不足 / Insufficient free space");
 for(size_t i=0;i<repair.size();i++){auto& e=repair[i];auto dest=app/fs::path(wide(e.name));fs::create_directories(dest.parent_path());auto temp=dest;temp+=L".sct-part";safePath(app,fs::relative(temp,app));progress(L"释放 / 修复 "+std::to_wstring(i+1)+L" / "+std::to_wstring(repair.size())+L"  "+wide(e.name),(int)((i+1)*100/repair.size()));try{Handle output(CreateFileW(temp.c_str(),GENERIC_WRITE,0,0,CREATE_ALWAYS,FILE_ATTRIBUTE_NORMAL,0));if(output.h==INVALID_HANDLE_VALUE)fail("Cannot write output");int index=mz_zip_reader_locate_file(&zip,e.name.c_str(),0,0);if(index<0||!mz_zip_reader_extract_to_callback(&zip,index,writeZip,&output.h,0))throw std::runtime_error("ZIP extraction / CRC failed: "+e.name);FlushFileBuffers(output.h);}catch(...){DeleteFileW(temp.c_str());throw;}if(hashFile(temp,e.size)!=e.hash){DeleteFileW(temp.c_str());throw std::runtime_error("Extracted SHA-256 mismatch: "+e.name);}if(!MoveFileExW(temp.c_str(),dest.c_str(),MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH))fail("Cannot commit extracted file");repaired++;}
 writeText(app/L"payload.sha256",manifestText);writeText(app/L".complete",expected);fs::create_directories(data/L"cache/temp");fs::create_directories(data/L"cache/blender_config");fs::create_directories(data/L"exports");
 // Preferences are next to the distributor EXE, never under AppData or the registry.
 try{writeText(prefs,utf8(data.wstring()));}catch(...){if(!quiet)MessageBoxW(window_,L"EXE 所在目录不可写，无法记住位置。下次请选择同一数据目录；现有工具链可继续复用。",title,MB_OK|MB_ICONINFORMATION);}
 writeText(data/L"launcher-last-run.txt","version=0.10.10\npayload_sha256="+expected+"\nfiles="+std::to_string(entries.size())+"\nrepaired="+std::to_string(repaired)+"\napp="+utf8(app.wstring())+"\nstatus=verified\n");
 if(verifyOnly){result=0;}else{
 for(auto pair:std::vector<std::pair<const wchar_t*,const wchar_t*>>{{L"APPDATA",L"profile/AppData/Roaming"},{L"LOCALAPPDATA",L"profile/AppData/Local"},{L"USERPROFILE",L"profile"},{L"HOME",L"profile"},{L"DOTNET_CLI_HOME",L"dotnet"},{L"CUDA_CACHE_PATH",L"cuda"},{L"OPTIX_CACHE_PATH",L"optix"}}){auto dir=data/L"cache"/pair.second;fs::create_directories(dir);env(pair.first,dir);}env(L"SCT_CACHE_ROOT",data/L"cache");
 env(L"SCT_HOME",app);env(L"SCT_DATA_ROOT",data);env(L"SCT_CONFIG",data/L"settings.json");env(L"TEMP",data/L"cache/temp");env(L"TMP",data/L"cache/temp");env(L"DOTNET_BUNDLE_EXTRACT_BASE_DIR",data/L"cache/dotnet");env(L"BLENDER_USER_CONFIG",data/L"cache/blender_config");SetEnvironmentVariableW(L"PYTHONNOUSERSITE",L"1");SetEnvironmentVariableW(L"PYTHONDONTWRITEBYTECODE",L"1");
 auto program=app/L"SekiroCharacterToolkit.exe";std::wstring command=quote(program.wstring());for(auto& arg:forward)command+=L" "+quote(arg);STARTUPINFOW si{sizeof(si)};PROCESS_INFORMATION pi{};if(!CreateProcessW(program.c_str(),command.data(),0,0,FALSE,0,0,app.c_str(),&si,&pi))fail("Cannot launch application");CloseHandle(pi.hThread);Handle child(pi.hProcess);ShowWindow(window_,SW_HIDE);WaitForSingleObject(child.h,INFINITE);DWORD code;GetExitCodeProcess(child.h,&code);result=(int)code;if(code&&!quiet)MessageBoxW(0,L"主程序异常退出。请查看数据目录 cache/logs 内的错误日志。",title,MB_OK|MB_ICONERROR);
 }
 }catch(const std::exception& e){if(!data.empty()&&fs::exists(data)){try{writeText(data/L"launcher-error.txt",e.what());}catch(...){}}if(!quiet)MessageBoxW(window_,wide(e.what()).c_str(),title,MB_OK|MB_ICONERROR);result=cancelled?2:1;}if(window_)DestroyWindow(window_);CoUninitialize();return result;}
