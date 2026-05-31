from __future__ import annotations
from typing import Dict, List, Set

class StdlibSymbolTable:
    """
    Static, curated symbol tables for standard libraries that ship with each language runtime.
    These are bundled directly and do not require network access.
    """

    # Seeding with common symbols for each language
    _TABLES: Dict[str, Dict[str, List[str]]] = {
        "python": {
            "json": ["dumps", "loads", "JSONEncoder", "JSONDecoder", "dump", "load"],
            "os": ["path", "environ", "getenv", "system", "mkdir", "remove", "rename", "walk"],
            "os.path": ["join", "exists", "isdir", "isfile", "abspath", "dirname", "basename", "split"],
            "pathlib": ["Path", "PurePath", "PosixPath", "WindowsPath"],
            "re": ["compile", "search", "match", "findall", "sub", "split"],
            "datetime": ["datetime", "date", "time", "timedelta", "timezone"],
            "sys": ["argv", "exit", "path", "modules", "stdin", "stdout", "stderr"],
            "typing": ["Optional", "Union", "List", "Dict", "Any", "Callable", "Iterable", "TypeVar"],
            "collections": ["defaultdict", "Counter", "deque", "namedtuple", "OrderedDict"],
            "math": ["sqrt", "sin", "cos", "tan", "pi", "e", "floor", "ceil"],
            "time": ["time", "sleep", "strftime", "strptime", "gmtime", "localtime"],
            "threading": ["Thread", "Lock", "RLock", "Condition", "Event", "Semaphore"],
            "subprocess": ["run", "Popen", "PIPE", "call", "check_call", "check_output"],
            "logging": ["getLogger", "basicConfig", "info", "warning", "error", "debug", "critical"],
        },
        "javascript": {
            "fs": ["readFile", "writeFile", "readFileSync", "writeFileSync", "stat", "readdir"],
            "path": ["join", "resolve", "dirname", "basename", "extname", "parse"],
            "http": ["createServer", "request", "get", "IncomingMessage", "ServerResponse"],
            "https": ["createServer", "request", "get"],
            "crypto": ["createHash", "createHmac", "randomBytes", "pbkdf2"],
            "stream": ["Readable", "Writable", "Duplex", "Transform", "pipeline"],
            "events": ["EventEmitter"],
            "os": ["platform", "release", "totalmem", "freemem", "cpus"],
            "util": ["promisify", "inherits", "inspect", "format"],
            "process": ["argv", "env", "exit", "stdin", "stdout", "stderr"],
        },
        "go": {
            "fmt": ["Println", "Printf", "Sprintf", "Errorf", "Scan", "Fprint"],
            "os": ["Open", "Create", "Args", "Exit", "Getenv", "Mkdir", "Remove", "Stat"],
            "io": ["ReadFull", "ReadAll", "Copy", "LimitReader", "NewSectionReader"],
            "net/http": ["Get", "Post", "HandleFunc", "ListenAndServe", "NewRequest", "Client"],
            "encoding/json": ["Marshal", "Unmarshal", "NewEncoder", "NewDecoder", "Indent"],
            "errors": ["New", "Unwrap", "Is", "As"],
            "context": ["Background", "TODO", "WithCancel", "WithDeadline", "WithTimeout", "WithValue"],
            "sync": ["WaitGroup", "Mutex", "RWMutex", "Cond", "Once", "Pool"],
            "time": ["Now", "Sleep", "Since", "Parse", "Format", "Tick"],
            "strings": ["Contains", "Split", "Join", "Replace", "ToLower", "ToUpper", "TrimSpace"],
        },
        "rust": {
            "std::collections": ["HashMap", "HashSet", "VecDeque", "BinaryHeap", "BTreeMap", "BTreeSet"],
            "std::io": ["Read", "Write", "BufReader", "BufWriter", "stdin", "stdout", "copy"],
            "std::fs": ["File", "read_to_string", "read", "write", "create_dir", "remove_file"],
            "std::path": ["Path", "PathBuf"],
            "std::sync": ["Arc", "Mutex", "RwLock", "Barrier", "Condvar", "mpsc"],
            "std::thread": ["spawn", "sleep", "current", "park"],
            "std::time": ["Duration", "Instant", "SystemTime"],
            "std::net": ["TcpListener", "TcpStream", "UdpSocket", "IpAddr"],
            "std::env": ["args", "vars", "var", "current_dir", "current_exe"],
            "std::process": ["Command", "Stdio", "exit", "Child"],
            "std::fmt": ["Debug", "Display", "Formatter", "Error"],
        }
    }

    def get_symbols(self, language: str, module: str) -> List[str]:
        """Get symbols for a specific module in a language."""
        lang_table = self._TABLES.get(language.lower(), {})
        return lang_table.get(module, [])

    def get_all_modules(self, language: str) -> Dict[str, List[str]]:
        """Get all registered modules and their symbols for a language."""
        return self._TABLES.get(language.lower(), {})

    def is_stdlib_module(self, language: str, module_name: str) -> bool:
        """Check if a module name belongs to the standard library of a language."""
        return module_name in self._TABLES.get(language.lower(), {})
