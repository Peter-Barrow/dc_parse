from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from dc_parse import create_config_hierarchy

if __name__ == '__main__':

    class LogLevel(Enum):
        DEBUG = 'debug'
        INFO = 'info'
        WARNING = 'warning'
        ERROR = 'error'

    @dataclass
    class DatabaseCredentials:
        """Database authentication credentials"""

        user: str = 'admin'
        password: Optional[str] = None

    @dataclass
    class DatabaseConfig:
        """Database configuration"""

        name: str = field(metadata={'help': 'Database name'})
        host: str = 'localhost'
        port: int = 5432
        credentials: DatabaseCredentials = field(
            default_factory=DatabaseCredentials,
            metadata={'help': 'Database authentication credentials'},
        )
        ssl: bool = True

    @dataclass
    class ServerConfig:
        """Web server configuration"""

        name: str = field(metadata={'help': 'Server name'})
        port: int = 8080
        host: str = 'localhost'
        debug: bool = False
        workers: int = field(
            default=4, metadata={'help': 'Number of worker processes'}
        )

    @dataclass
    class LoggingConfig:
        """Logging configuration"""

        level: LogLevel = LogLevel.INFO
        file: Optional[str] = None
        max_size: int = field(
            default=10485760, metadata={'help': 'Max log file size in bytes'}
        )

    print('=== Nested Dataclass and JSON Support Demo ===\n')

    # Create a parser with built-in config management
    # Use prefixes to avoid naming conflicts
    parser, parse_fn = create_config_hierarchy(
        (ServerConfig, {'prefix': 'server-'}),
        (DatabaseConfig, {'prefix': 'db-'}),
        (LoggingConfig, {'prefix': 'log-'}),
    )

    print('1. Generate YAML config file:')
    print('   python myapp.py --generate-config myapp.yaml')
    try:
        configs = parse_fn(['--generate-config', 'example_generated.yaml'])
        if configs is None:
            print('   [PASS] YAML config file generated\n')
        else:
            print('   [FAIL] Expected None return for --generate-config\n')
    except Exception as e:
        print(f'   [FAIL] Error: {e}\n')

    print('2. Generate JSON config file:')
    print('   python myapp.py --generate-json-config myapp.json')
    try:
        configs = parse_fn(['--generate-json-config', 'example_generated.json'])
        if configs is None:
            print('   [PASS] JSON config file generated\n')
        else:
            print('   [FAIL] Expected None return for --generate-json-config\n')
    except Exception as e:
        print(f'   [FAIL] Error: {e}\n')

    print('3. Show nested dataclass structure:')
    try:
        # Test loading the JSON config
        test_configs = parse_fn([
            '--config',
            'example_generated.json',
            '--server-name',
            'test-app',
            '--db-name',
            'test-db',
        ])

        if test_configs:
            print(
                '[PASS] Successfully loaded JSON config with nested dataclass:'
            )
            print(
                f'   Server: {test_configs["ServerConfig"].name}:{test_configs["ServerConfig"].port}'
            )
            db = test_configs['DatabaseConfig']
            print(f'   Database: {db.name}@{db.host}')
            print(
                f'   DB Credentials: user={db.credentials.user}, password={db.credentials.password}'
            )
            print(
                '   Note: DatabaseConfig.credentials is a nested dataclass!\n'
            )

    except Exception as e:
        print(
            f"Config file test failed (expected if file doesn't exist): {e}\n"
        )

    print('4. Test help (should work without required args):')
    try:
        result = parse_fn(['--help'])
        print('   [PASS] Help displayed (function returned None)\n')
    except SystemExit:
        print('   [PASS] Help displayed (argparse exit)\n')
    except Exception as e:
        print(f'   [FAIL] Error: {e}\n')

    print(
        '\nRun with --help to see all options including nested dataclass fields!'
    )
