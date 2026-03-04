import argparse
from dataclasses import fields, is_dataclass, MISSING
import inspect
from typing import (
    get_type_hints,
    get_origin,
    get_args,
    Union,
    Optional,
    List,
    Dict,
    Tuple,
    Any,
    Callable,
)
from enum import Enum
from pathlib import Path
import yaml
import json

__all__ = [
    "dataclass_to_argparse",
    "args_to_dataclass",
    "compose_dataclass_argparse",
    "dataclasses_to_config_file",
    "config_file_to_dataclasses",
    "load_config_file",
    "save_config_file",
    "parse_with_config_management",
    "parse_composed_args",
    "create_config_hierarchy",
    "create_simple_config_hierarchy",
]


def dataclass_to_argparse(
    cls,
    parser=None,
    prefix="",
    exclude_fields=None,
    allow_config_defaults=False,
):
    """
    Convert a dataclass to argparse arguments.

    Args:
        cls: The dataclass to convert
        parser: Existing ArgumentParser to add to (creates new if None)
        prefix: Prefix for argument names (useful for nested dataclasses)
        exclude_fields: Set of field names to exclude
        allow_config_defaults: If True, don't mark fields as required (for config file support)

    Returns:
        ArgumentParser instance
    """
    if not is_dataclass(cls):
        raise ValueError(f"{cls} is not a dataclass")

    if parser is None:
        parser = argparse.ArgumentParser(description=inspect.getdoc(cls))

    exclude_fields = exclude_fields or set()
    type_hints = get_type_hints(cls)

    for field in fields(cls):
        if field.name in exclude_fields:
            continue

        field_type = type_hints.get(field.name, field.type)
        arg_name = f"--{prefix}{field.name}".replace("_", "-")

        # Get help text from field metadata or docstring
        help_text = field.metadata.get("help", "") or field.metadata.get(
            "description", ""
        )

        # Determine if field is optional (has default or is Optional type)
        has_default = field.default != MISSING or field.default_factory != MISSING
        is_optional_type = _is_optional_type(field_type)

        # Handle different field types
        if _is_dataclass_type(field_type):
            # Recursively handle nested dataclass
            nested_cls = _get_dataclass_type(field_type)
            nested_prefix = f"{prefix}{field.name}_"
            dataclass_to_argparse(
                nested_cls,
                parser=parser,
                prefix=nested_prefix,
                exclude_fields=None,
                allow_config_defaults=allow_config_defaults,
            )
        elif _is_bool_type(field_type):
            _add_bool_argument(
                parser,
                field,
                arg_name,
                help_text,
                has_default,
                allow_config_defaults,
            )
        elif _is_list_type(field_type):
            _add_list_argument(
                parser,
                field,
                field_type,
                arg_name,
                help_text,
                has_default,
                allow_config_defaults,
            )
        elif _is_enum_type(field_type):
            _add_enum_argument(
                parser,
                field,
                field_type,
                arg_name,
                help_text,
                has_default,
                allow_config_defaults,
            )
        else:
            _add_standard_argument(
                parser,
                field,
                field_type,
                arg_name,
                help_text,
                has_default,
                is_optional_type,
                allow_config_defaults,
            )

    return parser


def _is_optional_type(field_type):
    """Check if type is Optional[T] (Union[T, None])"""
    origin = get_origin(field_type)
    if origin is Union:
        args = get_args(field_type)
        return len(args) == 2 and type(None) in args
    return False


def _is_bool_type(field_type):
    """Check if type is bool or Optional[bool]"""
    if field_type is bool:
        return True
    if _is_optional_type(field_type):
        args = get_args(field_type)
        non_none_type = next((arg for arg in args if arg is not type(None)), None)
        return non_none_type is bool
    return False


def _is_list_type(field_type):
    """Check if type is a list/sequence type"""
    # First check if it's directly a list type
    origin = get_origin(field_type)
    if origin in (list, List) or (
        hasattr(field_type, "__origin__") and field_type.__origin__ in (list, List)
    ):
        return True

    # Check if it's Optional[List[T]] by looking inside Union types
    if origin is Union:
        args = get_args(field_type)
        for arg in args:
            if arg is not type(None):  # Skip None type
                inner_origin = get_origin(arg)
                if inner_origin in (list, List) or (
                    hasattr(arg, "__origin__") and arg.__origin__ in (list, List)
                ):
                    return True

    return False


def _is_enum_type(field_type):
    """Check if type is an Enum"""
    try:
        return issubclass(field_type, Enum)
    except TypeError:
        return False


def _is_dataclass_type(field_type):
    """Check if type is a dataclass or Optional[dataclass]"""
    # First check if it's directly a dataclass
    if is_dataclass(field_type):
        return True

    # Check if it's Optional[SomeDataclass]
    if _is_optional_type(field_type):
        args = get_args(field_type)
        for arg in args:
            if arg is not type(None) and is_dataclass(arg):
                return True

    return False


def _is_tuple_type(field_type):
    """Check if type is a tuple type"""
    origin = get_origin(field_type)
    return origin is tuple


def _get_tuple_args(field_type):
    """Get the tuple element types"""
    return get_args(field_type)


def _get_dataclass_type(field_type):
    """Extract the dataclass type from field_type, handling Optional types"""
    if is_dataclass(field_type):
        return field_type

    if _is_optional_type(field_type):
        args = get_args(field_type)
        for arg in args:
            if arg is not type(None) and is_dataclass(arg):
                return arg

    return None


def _add_bool_argument(
    parser, field, arg_name, help_text, has_default, allow_config_defaults=False
):
    """Add boolean argument with proper store_true/store_false logic"""
    default_value = _get_default_value(field)

    # Add default info to help text
    if has_default:
        default_text = f" (default: {default_value})"
        help_text = (help_text or f"Enable {field.name}") + default_text

    if has_default and default_value is False:
        # Default is False, so flag should set to True
        parser.add_argument(
            arg_name,
            action="store_true",
            help=help_text or f"Enable {field.name}",
            default=default_value,
        )
    elif has_default and default_value is True:
        # Default is True, so we need both --flag and --no-flag
        parser.add_argument(
            arg_name,
            action="store_true",
            dest=field.name,
            help=help_text or f"Enable {field.name}",
        )
        parser.add_argument(
            f"--no-{arg_name[2:]}",
            action="store_false",
            dest=field.name,
            help=f"Disable {field.name}",
        )
        parser.set_defaults(**{field.name: default_value})
    else:
        # No default - require explicit True/False unless config defaults allowed
        parser.add_argument(
            arg_name,
            type=lambda x: x.lower() in ("true", "1", "yes", "on"),
            help=help_text or f"{field.name} (true/false)",
            required=not allow_config_defaults,
        )


def _add_list_argument(
    parser,
    field,
    field_type,
    arg_name,
    help_text,
    has_default,
    allow_config_defaults=False,
):
    """Add list/sequence argument"""
    # Extract the actual list type from Optional[List[T]] if needed
    list_type = field_type
    if _is_optional_type(field_type):
        args = get_args(field_type)
        for arg in args:
            if arg is not type(None):
                list_type = arg
                break

    # Get the inner type of the list
    args = get_args(list_type)
    inner_type = args[0] if args else str

    # Convert inner type for argparse
    if inner_type in (int, float, str):
        arg_type = inner_type
    else:
        arg_type = str

    default_value = _get_default_value(field) if has_default else None

    # Add default info to help text
    base_help = help_text or f"List of {inner_type.__name__} values"
    if has_default:
        default_text = f" (default: {default_value})"
        help_text = base_help + default_text
    else:
        help_text = base_help

    parser.add_argument(
        arg_name,
        type=arg_type,
        nargs="*" if (has_default or allow_config_defaults) else "+",
        help=help_text,
        default=default_value,
    )


def _add_enum_argument(
    parser,
    field,
    field_type,
    arg_name,
    help_text,
    has_default,
    allow_config_defaults=False,
):
    """Add enum argument with choices"""
    choices = [e.value for e in field_type]
    default_value = _get_default_value(field) if has_default else None

    # Convert default to string value if it's an enum
    if default_value and isinstance(default_value, Enum):
        default_value = default_value.value

    # Add default info to help text
    base_help = help_text or f"Choose from: {', '.join(map(str, choices))}"
    if has_default:
        default_text = f" (default: {default_value})"
        help_text = base_help + default_text
    else:
        help_text = base_help

    parser.add_argument(
        arg_name,
        choices=choices,
        help=help_text,
        default=default_value,
        required=(not has_default) and (not allow_config_defaults),
    )


def _add_standard_argument(
    parser,
    field,
    field_type,
    arg_name,
    help_text,
    has_default,
    is_optional_type,
    allow_config_defaults=False,
):
    """Add standard argument (str, int, float, etc.)"""
    # Handle Optional types
    if is_optional_type:
        args = get_args(field_type)
        actual_type = next((arg for arg in args if arg is not type(None)), str)
    else:
        actual_type = field_type

    # Convert type for argparse
    if actual_type in (int, float, str):
        arg_type = actual_type
    else:
        arg_type = str

    default_value = _get_default_value(field) if has_default else None

    # Add default info to help text
    base_help = help_text or f"{field.name} ({actual_type.__name__})"
    if has_default:
        default_text = f" (default: {default_value})"
        help_text = base_help + default_text
    else:
        help_text = base_help

    parser.add_argument(
        arg_name,
        type=arg_type,
        help=help_text,
        default=default_value,
        required=(not has_default)
        and (not is_optional_type)
        and (not allow_config_defaults),
    )


def _get_default_value(field):
    """Get the default value for a field"""
    if field.default != MISSING:
        return field.default
    elif field.default_factory != MISSING:
        return field.default_factory()
    return None


def args_to_dataclass(cls, args):
    """Convert parsed arguments back to dataclass instance.

    Args:
        cls: The dataclass type to instantiate
        args: Either an argparse.Namespace or a dictionary of arguments

    Returns:
        An instance of the dataclass cls
    """
    if isinstance(args, argparse.Namespace):
        args = vars(args)

    # Filter args to only include fields that exist in the dataclass
    field_names = {f.name for f in fields(cls)}
    filtered_args = {k: v for k, v in args.items() if k in field_names}

    return cls(**filtered_args)


def compose_dataclass_argparse(
    *dataclass_configs: Union[Any, Tuple[Any, Dict[str, Any]]],
    parser: Optional[argparse.ArgumentParser] = None,
    use_groups: bool = True,
    add_config_options: bool = True,
) -> Tuple[argparse.ArgumentParser, List[Tuple[Any, Dict[str, Any]]]]:
    """
    Compose multiple dataclasses into a single ArgumentParser.

    Args:
        *dataclass_configs: Either dataclass types or tuples of (dataclass,
            config_dict)
        parser: Existing ArgumentParser to add to (creates new if None)
        use_groups: Whether to use argument groups for organization
        add_config_options: Whether to add --config, --generate-config,
            --update-config options

    Returns:
        Tuple of (ArgumentParser, list of (dataclass, config) tuples for parsing
            back)
    """
    if parser is None:
        parser = argparse.ArgumentParser()

    configs = []

    for config in dataclass_configs:
        if isinstance(config, tuple):
            cls, config_dict = config
            config_dict = config_dict or {}
        else:
            cls = config
            config_dict = {}

        if not is_dataclass(cls):
            raise ValueError(f"{cls} is not a dataclass")

        # Set defaults for config
        config_dict.setdefault("prefix", "")
        config_dict.setdefault("group_title", cls.__name__)
        config_dict.setdefault(
            "group_description",
            inspect.getdoc(cls) or f"{cls.__name__} configuration",
        )

        configs.append((cls, config_dict))

    # Add config file management options
    if add_config_options:
        config_group = parser.add_argument_group(
            "Configuration File Options",
            "Options for managing configuration files",
        )

        config_group.add_argument(
            "--generate-config",
            metavar="PATH",
            help="Generate a YAML config file template and exit",
        )

        config_group.add_argument(
            "--config",
            metavar="PATH",
            help="Load configuration from YAML or JSON file",
        )

        config_group.add_argument(
            "--update-config",
            action="store_true",
            help="Update the config file with any CLI arguments provided (requires --config)",
        )

        config_group.add_argument(
            "--print-config",
            action="store_true",
            help="Print the effective configuration and exit",
        )

    # Check for naming conflicts and suggest prefixes
    _check_naming_conflicts(configs)

    # Add arguments for each dataclass
    for cls, config_dict in configs:
        if use_groups:
            group = parser.add_argument_group(
                config_dict["group_title"], config_dict["group_description"]
            )
            dataclass_to_argparse(
                cls,
                parser=group,
                prefix=config_dict["prefix"],
                exclude_fields=config_dict.get("exclude_fields"),
                allow_config_defaults=add_config_options,
            )
        else:
            dataclass_to_argparse(
                cls,
                parser=parser,
                prefix=config_dict["prefix"],
                exclude_fields=config_dict.get("exclude_fields"),
                allow_config_defaults=add_config_options,
            )

    return parser, configs


def _check_naming_conflicts(configs):
    """Check for potential naming conflicts between dataclasses"""
    all_args = set()
    conflicts = []

    for cls, config_dict in configs:
        prefix = config_dict["prefix"]
        exclude_fields = config_dict.get("exclude_fields", set())

        for field in fields(cls):
            if field.name not in exclude_fields:
                arg_name = f"--{prefix}{field.name}".replace("_", "-")
                if arg_name in all_args:
                    conflicts.append(arg_name)
                all_args.add(arg_name)

    if conflicts:
        msg = (
            f"Naming conflicts detected: {conflicts}."
            + " Use different prefixes or exclude conflicting fields."
        )
        raise ValueError(msg)


def dataclasses_to_config_file(
    output_path: Union[str, Path],
    *dataclass_configs,
    include_comments: bool = True,
) -> None:
    """
    Generate a config file template from
    Supports both YAML and JSON formats based on file extension.

    Args:
        output_path: Path to write the config file (.yaml, .yml, or .json)
        *dataclass_configs: Either dataclass types or tuples of (dataclass,
            config_dict)
        include_comments: Whether to include help text and type info as
            comments (YAML only)
    """
    output_path = Path(output_path)
    ext = output_path.suffix.lower()

    config_data = {}
    comments = {}

    # Process dataclass configs same as compose_dataclass_argparse
    configs = []
    for config in dataclass_configs:
        if isinstance(config, tuple):
            cls, config_dict = config
            config_dict = config_dict or {}
        else:
            cls = config
            config_dict = {}

        if not is_dataclass(cls):
            raise ValueError(f"{cls} is not a dataclass")

        # Set defaults for config
        class_name = cls.__name__.lower()
        config_dict.setdefault("prefix", "")
        config_dict.setdefault("section_name", class_name)

        configs.append((cls, config_dict))

    # Generate config data for each dataclass
    for cls, config_dict in configs:
        section_name = config_dict.get("section_name", cls.__name__.lower())
        prefix = config_dict.get("prefix", "")
        exclude_fields = config_dict.get("exclude_fields", set())

        section_data = {}
        section_comments = {}

        if include_comments:
            class_doc = inspect.getdoc(cls)
            if class_doc:
                section_comments["_section_doc"] = class_doc

        type_hints = get_type_hints(cls)

        for field in fields(cls):
            if field.name in exclude_fields:
                continue

            # Get default value
            default_value = _get_default_value(field)
            field_type = type_hints.get(field.name, field.type)

            # Handle nested dataclasses - create nested dict structure
            if _is_dataclass_type(field_type) and default_value is not None:
                if is_dataclass(default_value):
                    default_value = _dataclass_to_dict(default_value)
                else:
                    # Create empty nested structure if no default
                    nested_cls = _get_dataclass_type(field_type)
                    if nested_cls:
                        default_instance = nested_cls()
                        default_value = _dataclass_to_dict(default_instance)

            # Handle lists that may contain dataclasses
            if isinstance(default_value, list) and default_value:
                default_value = [
                    _dataclass_to_dict(item) if is_dataclass(item) else item
                    for item in default_value
                ]

            # Handle enum defaults
            if isinstance(default_value, Enum):
                default_value = default_value.value

            # Store the value
            field_key = f"{prefix}{field.name}" if prefix else field.name
            section_data[field_key] = default_value

            # Add comments with type and help info
            if include_comments:
                help_text = field.metadata.get("help", "") or field.metadata.get(
                    "description", ""
                )

                comment_parts = []
                if help_text:
                    comment_parts.append(help_text)

                # Add type information
                type_str = _format_type_for_comment(field_type)
                comment_parts.append(f"Type: {type_str}")

                # Add choices for enums
                if _is_enum_type(field_type):
                    choices = [e.value for e in field_type]
                    comment_parts.append(f"Choices: {choices}")

                section_comments[field_key] = " | ".join(comment_parts)

        config_data[section_name] = section_data
        if include_comments:
            comments[section_name] = section_comments

    # Save in appropriate format
    if ext == ".json":
        with open(output_path, "w") as f:
            json.dump(config_data, f, indent=2)
        print(f"JSON config file template written to: {output_path}")
    elif ext in (".yaml", ".yml"):
        # Write to file with comments
        with open(output_path, "w") as f:
            if include_comments:
                f.write("# Configuration file generated from dataclasses\n")
                f.write(
                    "# Edit values as needed, remove sections you don't want to override\n\n"
                )

            for section_name, section_data in config_data.items():
                section_comments = comments.get(section_name, {})

                # Write section header with documentation
                if include_comments and "_section_doc" in section_comments:
                    f.write(f"# {section_comments['_section_doc']}\n")
                f.write(f"{section_name}:\n")

                # Use yaml.safe_dump for clean YAML without Python object tags
                yaml_str = yaml.safe_dump(
                    section_data,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False,
                )

                # Add comments for top-level keys
                for line in yaml_str.strip().split("\n"):
                    if include_comments and ":" in line:
                        key = line.split(":")[0].strip()
                        if key in section_comments:
                            f.write(f"  # {section_comments[key]}\n")
                    f.write(f"  {line}\n")

                f.write("\n")

        print(f"YAML config file template written to: {output_path}")
    else:
        raise ValueError(
            f"Unsupported file extension: {ext}. Use .json, .yaml, or .yml"
        )


def _format_type_for_comment(field_type):
    """Format type information for config file comments"""
    if field_type in (int, float, str, bool):
        return field_type.__name__
    elif _is_dataclass_type(field_type):
        dataclass_cls = _get_dataclass_type(field_type)
        return f"Nested[{dataclass_cls.__name__}]" if dataclass_cls else "Dataclass"
    elif _is_tuple_type(field_type):
        tuple_args = _get_tuple_args(field_type)
        if tuple_args:
            arg_strs = [_format_type_for_comment(arg) for arg in tuple_args]
            return f"Tuple[{', '.join(arg_strs)}]"
        return "Tuple"
    elif _is_optional_type(field_type):
        args = get_args(field_type)
        inner_type = next((arg for arg in args if arg is not type(None)), str)
        return f"Optional[{_format_type_for_comment(inner_type)}]"
    elif _is_list_type(field_type):
        args = get_args(field_type)
        if args:
            return f"List[{_format_type_for_comment(args[0])}]"
        return "List"
    elif _is_enum_type(field_type):
        return field_type.__name__
    else:
        return str(field_type)


def config_file_to_dataclasses(
    config_path: Union[str, Path], *dataclass_configs
) -> Dict[str, Any]:
    """
    Read a config file (YAML or JSON) and convert to dataclass instances.
    File format is determined by extension.

    Args:
        config_path: Path to the config file (.yaml, .yml, or .json)
        *dataclass_configs: Same format as dataclasses_to_config_file

    Returns:
        Mapping of dataclass names to their instances
    """
    return load_config_file(config_path, *dataclass_configs)


def _convert_config_value(value, field_type):
    """Convert a value from config file to the appropriate type"""
    if value is None:
        return None

    # Handle Optional types
    if _is_optional_type(field_type):
        if value is None:
            return None
        args = get_args(field_type)
        actual_type = next((arg for arg in args if arg is not type(None)), str)
        return _convert_config_value(value, actual_type)

    # Handle nested dataclass types
    if _is_dataclass_type(field_type):
        dataclass_cls = _get_dataclass_type(field_type)
        if isinstance(value, dict):
            # Recursively convert nested dict to dataclass
            return _dict_to_dataclass(value, dataclass_cls)
        return value

    # Handle tuple types (including tuples of dataclasses)
    if _is_tuple_type(field_type):
        if not isinstance(value, (list, tuple)):
            return value

        tuple_args = _get_tuple_args(field_type)
        if not tuple_args:
            return tuple(value)

        # Convert each element according to its type
        # If all types are the same (e.g., Tuple[int, int, int]), use the first type
        # If types differ (e.g., Tuple[int, str, bool]), use corresponding types
        converted = []
        for i, item in enumerate(value):
            # Use the corresponding type if available, otherwise use the last type
            item_type = tuple_args[min(i, len(tuple_args) - 1)]
            converted.append(_convert_config_value(item, item_type))

        return tuple(converted)

    # Handle enum types
    if _is_enum_type(field_type):
        if isinstance(value, str):
            # Find enum member by value
            for enum_member in field_type:
                if enum_member.value == value:
                    return enum_member
            raise ValueError(f"Invalid enum value '{value}' for {field_type}")
        return value

    # Handle list types
    if _is_list_type(field_type):
        if not isinstance(value, list):
            return value

        # Get inner type
        args = get_args(field_type)
        if args:
            inner_type = args[0]
            return [_convert_config_value(item, inner_type) for item in value]
        return value

    # Handle basic types
    if field_type in (int, float, str, bool):
        if isinstance(value, field_type):
            return value
        # Try to convert
        try:
            return field_type(value)
        except (ValueError, TypeError):
            return value

    return value


def load_config_file(
    config_path: Union[str, Path], *dataclass_configs
) -> Dict[str, Any]:
    """
    Load a config file (YAML or JSON) and convert to dataclass instances.
    File format is determined by extension (.yaml, .yml, or .json).

    Args:
        config_path: Path to the config file
        *dataclass_configs: Same format as dataclasses_to_config_file

    Returns:
        Mapping of dataclass names to their instances
    """
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    # Determine file format from extension
    ext = config_path.suffix.lower()

    with open(config_path, "r") as f:
        if ext == ".json":
            config_data = json.load(f)
        elif ext in (".yaml", ".yml"):
            config_data = yaml.safe_load(f) or {}
        else:
            raise ValueError(
                f"Unsupported config file format: {ext}. Use .json, .yaml, or .yml"
            )

    # Process dataclass configs (same logic as before)
    configs = []
    for config in dataclass_configs:
        if isinstance(config, tuple):
            cls, config_dict = config
            config_dict = config_dict or {}
        else:
            cls = config
            config_dict = {}

        if not is_dataclass(cls):
            raise ValueError(f"{cls} is not a dataclass")

        # Set defaults
        class_name = cls.__name__.lower()
        config_dict.setdefault("prefix", "")  # Default to empty prefix for consistency
        config_dict.setdefault("section_name", class_name)

        configs.append((cls, config_dict))

    results = {}
    type_hints_cache = {}

    for cls, config_dict in configs:
        section_name = config_dict.get("section_name", cls.__name__.lower())
        prefix = config_dict.get("prefix", "")
        exclude_fields = config_dict.get("exclude_fields", set())

        section_data = config_data.get(section_name, {})
        class_args = {}

        # Get type hints for this class
        if cls not in type_hints_cache:
            type_hints_cache[cls] = get_type_hints(cls)
        type_hints = type_hints_cache[cls]

        for field in fields(cls):
            if field.name in exclude_fields:
                continue

            field_key = f"{prefix}{field.name}" if prefix else field.name

            if field_key in section_data:
                value = section_data[field_key]

                # Convert value to appropriate type
                field_type = type_hints.get(field.name, field.type)
                converted_value = _convert_config_value(value, field_type)
                class_args[field.name] = converted_value

        # Create instance with config values
        try:
            instance = cls(**class_args)
            results[cls.__name__] = instance
        except TypeError as e:
            raise ValueError(
                f"Failed to create {cls.__name__} instance from config: {e}"
            )

    return results


def save_config_file(
    output_path: Union[str, Path],
    instances: Dict[str, Any],
    dataclass_configs: List[Tuple[Any, Dict[str, Any]]],
    include_comments: bool = True,
) -> None:
    """
    Save dataclass instances to a config file (YAML or JSON).
    File format is determined by extension.

    Args:
        output_path: Path to write the config file
        instances: Dict mapping dataclass names to instances
        dataclass_configs: List of (dataclass, config_dict) tuples
        include_comments: Whether to include help text (YAML only)
    """
    output_path = Path(output_path)
    ext = output_path.suffix.lower()

    if ext == ".json":
        _save_json_config(output_path, instances, dataclass_configs)
    elif ext in (".yaml", ".yml"):
        _save_yaml_config(output_path, instances, dataclass_configs, include_comments)
    else:
        raise ValueError(
            f"Unsupported config file format: {ext}. Use .json, .yaml, or .yml"
        )


def _save_json_config(output_path, instances, dataclass_configs):
    """Save config to JSON file with nested structure"""
    config_data = {}

    for (cls, config_dict), (name, instance) in zip(
        dataclass_configs, instances.items()
    ):
        section_name = config_dict["section_name"]
        prefix = config_dict["prefix"]
        exclude_fields = config_dict.get("exclude_fields", set())

        section_data = {}

        for field in fields(cls):
            if field.name in exclude_fields:
                continue

            field_key = f"{prefix}{field.name}" if prefix else field.name
            value = getattr(instance, field.name)

            # Handle nested dataclasses
            if is_dataclass(value):
                section_data[field_key] = _dataclass_to_dict(value)
            # Handle tuples (including tuples of dataclasses)
            elif isinstance(value, tuple):
                section_data[field_key] = [
                    _dataclass_to_dict(item) if is_dataclass(item) else item
                    for item in value
                ]
            # Handle enums
            elif isinstance(value, Enum):
                section_data[field_key] = value.value
            # Handle lists
            elif isinstance(value, list):
                section_data[field_key] = [
                    _dataclass_to_dict(item) if is_dataclass(item) else item
                    for item in value
                ]
            else:
                section_data[field_key] = value

        config_data[section_name] = section_data

    with open(output_path, "w") as f:
        json.dump(config_data, f, indent=2)

    print(f"Config file written to: {output_path}")


def _save_yaml_config(output_path, instances, dataclass_configs, include_comments):
    """Save config to YAML file with comments and nested structure"""
    config_data = {}
    comments = {}

    for (cls, config_dict), (name, instance) in zip(
        dataclass_configs, instances.items()
    ):
        section_name = config_dict["section_name"]
        prefix = config_dict["prefix"]
        exclude_fields = config_dict.get("exclude_fields", set())

        section_data = {}
        section_comments = {}

        # Add section documentation
        if include_comments:
            class_doc = inspect.getdoc(cls)
            if class_doc:
                section_comments["_section_doc"] = class_doc

        type_hints = get_type_hints(cls)

        for field in fields(cls):
            if field.name in exclude_fields:
                continue

            field_key = f"{prefix}{field.name}" if prefix else field.name
            value = getattr(instance, field.name)

            # Handle nested dataclasses
            if is_dataclass(value):
                section_data[field_key] = _dataclass_to_dict(value)
            # Handle tuples (including tuples of dataclasses)
            elif isinstance(value, tuple):
                section_data[field_key] = [
                    _dataclass_to_dict(item) if is_dataclass(item) else item
                    for item in value
                ]
            # Handle enums
            elif isinstance(value, Enum):
                section_data[field_key] = value.value
            # Handle lists
            elif isinstance(value, list):
                section_data[field_key] = [
                    _dataclass_to_dict(item) if is_dataclass(item) else item
                    for item in value
                ]
            else:
                section_data[field_key] = value

            # Add comments with type and help info
            if include_comments:
                field_type = type_hints.get(field.name, field.type)
                help_text = field.metadata.get("help", "") or field.metadata.get(
                    "description", ""
                )

                comment_parts = []
                if help_text:
                    comment_parts.append(help_text)

                # Add type information
                type_str = _format_type_for_comment(field_type)
                comment_parts.append(f"Type: {type_str}")

                # Add choices for enums
                if _is_enum_type(field_type):
                    choices = [e.value for e in field_type]
                    comment_parts.append(f"Choices: {choices}")

                section_comments[field_key] = " | ".join(comment_parts)

        config_data[section_name] = section_data
        comments[section_name] = section_comments

    # Write to file with comments
    with open(output_path, "w") as f:
        f.write("# Configuration file\n")
        f.write("# Updated automatically\n\n")

        for section_name, section_data in config_data.items():
            section_comments = comments.get(section_name, {})

            # Write section header with documentation
            if "_section_doc" in section_comments:
                f.write(f"# {section_comments['_section_doc']}\n")
            f.write(f"{section_name}:\n")

            # Use yaml.safe_dump for clean YAML without Python object tags
            yaml_str = yaml.safe_dump(
                section_data,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
            )

            # Add comments inline where possible
            for line in yaml_str.strip().split("\n"):
                if include_comments:
                    # Extract key from line
                    if ":" in line:
                        key = line.split(":")[0].strip()
                        if key in section_comments:
                            f.write(f"  # {section_comments[key]}\n")
                f.write(f"  {line}\n")

            f.write("\n")

    print(f"Config file written to: {output_path}")


def _dict_to_dataclass(data, dataclass_cls):
    """Convert a dictionary to a dataclass instance, handling nested structures"""
    if not is_dataclass(dataclass_cls):
        raise ValueError(f"{dataclass_cls} is not a dataclass")

    type_hints = get_type_hints(dataclass_cls)
    field_values = {}

    for field in fields(dataclass_cls):
        if field.name in data:
            field_type = type_hints.get(field.name, field.type)
            field_values[field.name] = _convert_config_value(
                data[field.name], field_type
            )

    return dataclass_cls(**field_values)


def _dataclass_to_dict(instance, include_none=True):
    """Convert a dataclass instance to a dictionary, handling nested structures"""
    if not is_dataclass(instance):
        raise ValueError(f"{instance} is not a dataclass instance")

    result = {}
    for field in fields(instance):
        value = getattr(instance, field.name)

        # Skip None values if requested
        if value is None and not include_none:
            continue

        # Handle nested dataclasses
        if is_dataclass(value):
            result[field.name] = _dataclass_to_dict(value, include_none)
        # Handle tuples (including tuples of dataclasses)
        elif isinstance(value, tuple):
            result[field.name] = [
                _dataclass_to_dict(item, include_none) if is_dataclass(item) else item
                for item in value
            ]
        # Handle enums
        elif isinstance(value, Enum):
            result[field.name] = value.value
        # Handle lists that might contain dataclasses
        elif isinstance(value, list):
            result[field.name] = [
                _dataclass_to_dict(item, include_none) if is_dataclass(item) else item
                for item in value
            ]
        else:
            result[field.name] = value

    return result


def parse_with_config_management(parser_configs, args=None):
    """
    Enhanced parser that handles config file generation, loading, and updating.

    This is the main entry point for applications using the config system.

    Args:
        parser_configs: The configs returned by compose_dataclass_argparse
        args: CLI arguments to parse (uses sys.argv if None)

    Returns:
        dict: Mapping of dataclass names to their instances, or None if program should exit
    """
    import sys

    if args is None:
        args = sys.argv[1:]

    parser, configs = parser_configs

    # CRITICAL: Handle --generate-config and --generate-json-config as the very first check
    # This bypasses all argument validation completely
    if len(args) >= 2 and (
        args[0] == "--generate-config" or args[0] == "--generate-json-config"
    ):
        config_path = args[1]
        print(f"Generating config file template: {config_path}")

        try:
            # Convert configs to the format expected by dataclasses_to_config_file
            dataclass_configs = []
            for cls, config_dict in configs:
                # Use section names without dashes for config file
                section_name = cls.__name__.lower()
                prefix = config_dict["prefix"].replace("-", "_")

                file_config = {
                    "prefix": prefix,
                    "section_name": section_name,
                    "exclude_fields": config_dict.get("exclude_fields", set()),
                }
                dataclass_configs.append((cls, file_config))

            dataclasses_to_config_file(config_path, *dataclass_configs)
            return None  # Signal that program should exit

        except Exception as e:
            print(f"Error generating config file: {e}")
            sys.exit(1)

    # Handle --help before any validation
    if len(args) == 1 and (args[0] == "--help" or args[0] == "-h"):
        parser.print_help()
        return None

    # Load config file if specified to provide defaults BEFORE validation
    config_data = {}
    config_path = None

    if "--config" in args:
        try:
            config_index = args.index("--config")
            if config_index + 1 < len(args):
                config_path = args[config_index + 1]

                try:
                    # Convert configs for config file reading
                    dataclass_configs = []
                    for cls, config_dict in configs:
                        section_name = cls.__name__.lower()
                        prefix = config_dict["prefix"].replace("-", "_")

                        file_config = {
                            "prefix": prefix,
                            "section_name": section_name,
                            "exclude_fields": config_dict.get("exclude_fields", set()),
                        }
                        dataclass_configs.append((cls, file_config))

                    config_instances = config_file_to_dataclasses(
                        config_path, *dataclass_configs
                    )

                    # Convert config instances to CLI argument format
                    for cls, config_dict in configs:
                        instance = config_instances.get(cls.__name__)
                        if instance:
                            prefix = config_dict["prefix"]
                            for field in fields(cls):
                                if field.name not in config_dict.get(
                                    "exclude_fields", set()
                                ):
                                    field_key = f"{prefix}{field.name}".replace(
                                        "-", "_"
                                    )
                                    value = getattr(instance, field.name)
                                    if value is not None:
                                        config_data[field_key] = value

                except Exception as e:
                    print(f"Error loading config file {config_path}: {e}")
                    sys.exit(1)
        except ValueError:
            pass  # --config not found

    # Set defaults from config file if available
    if config_data:
        parser.set_defaults(**config_data)

    # Special case: handle --print-config with config file (before full validation)
    if "--print-config" in args and config_path:
        try:
            dataclass_configs = []
            for cls, config_dict in configs:
                section_name = cls.__name__.lower()
                prefix = config_dict["prefix"].replace("-", "_")

                file_config = {
                    "prefix": prefix,
                    "section_name": section_name,
                    "exclude_fields": config_dict.get("exclude_fields", set()),
                }
                dataclass_configs.append((cls, file_config))

            config_instances = config_file_to_dataclasses(
                config_path, *dataclass_configs
            )

            print("Configuration from file:")
            for name, instance in config_instances.items():
                print(f"\n{name}:")
                for field in fields(instance.__class__):
                    value = getattr(instance, field.name)
                    print(f"  {field.name}: {value}")
            return None
        except Exception as e:
            print(f"Error reading config for --print-config: {e}")
            sys.exit(1)

    # NOW: Do normal argparse processing (only if we haven't returned yet)
    try:
        parsed_args = parser.parse_args(args)
    except SystemExit:
        # If parsing fails, re-raise to let argparse handle it
        raise

    # Get CLI arguments (excluding config management options)
    cli_data = {}
    for key, value in vars(parsed_args).items():
        if (
            key
            not in (
                "generate_config",
                "config",
                "update_config",
                "print_config",
            )
            and value is not None
        ):
            cli_data[key] = value

    # Combine config file and CLI data (CLI takes precedence)
    final_data = {**config_data, **cli_data}

    # Create final namespace
    final_namespace = argparse.Namespace(**final_data)

    # Parse back to dataclass instances
    instances = parse_composed_args((parser, configs), None, final_namespace)

    # Handle --print-config (full effective config including CLI overrides)
    if hasattr(parsed_args, "print_config") and parsed_args.print_config:
        print("Effective configuration:")
        for name, instance in instances.items():
            print(f"\n{name}:")
            for field in fields(instance.__class__):
                value = getattr(instance, field.name)
                print(f"  {field.name}: {value}")
        return None  # Signal that program should exit

    # Handle --update-config
    if hasattr(parsed_args, "update_config") and parsed_args.update_config:
        if not config_path:
            print(
                "Error: --update-config requires --config to specify the file to update"
            )
            sys.exit(1)

        print(f"Updating config file: {config_path}")

        # Generate updated config file with current effective values
        dataclass_configs = []
        for cls, config_dict in configs:
            section_name = cls.__name__.lower()
            prefix = config_dict["prefix"].replace("-", "_")

            file_config = {
                "prefix": prefix,
                "section_name": section_name,
                "exclude_fields": config_dict.get("exclude_fields", set()),
            }
            dataclass_configs.append((cls, file_config))

        # Write updated config using current instances
        _write_config_from_instances(config_path, instances, dataclass_configs)
        print(f"Config file updated: {config_path}")

    return instances


def _write_config_from_instances(config_path, instances, dataclass_configs):
    """Write a config file from dataclass instances"""
    save_config_file(config_path, instances, dataclass_configs, include_comments=True)


def parse_composed_args(
    parser_configs: Tuple[argparse.ArgumentParser, List[Tuple[Any, Dict[str, Any]]]],
    args: Optional[List[str]] = None,
    namespace: Optional[argparse.Namespace] = None,
) -> Dict[str, Any]:
    """
    Parse arguments and return instances of all composed

    Args:
        parser_configs: The configs list returned by compose_dataclass_argparse
        args: Arguments to parse (uses sys.argv if None)
        namespace: Pre-populated namespace to use instead of parsing

    Returns:
        Mapping of dataclass names to their instances
    """
    parser, configs = parser_configs

    if namespace is not None:
        parsed_args = namespace
    else:
        parsed_args = parser.parse_args(args)

    args_dict = vars(parsed_args)

    results = {}

    for cls, config_dict in configs:
        prefix = config_dict["prefix"]

        # Extract and reconstruct arguments for this dataclass (including nested ones)
        class_args = _extract_dataclass_args(cls, prefix, args_dict)

        # Create instance
        try:
            instance = cls(**class_args)
            results[cls.__name__] = instance
        except TypeError as e:
            raise ValueError(f"Failed to create {cls.__name__} instance: {e}")

    return results


def _extract_dataclass_args(cls, prefix, args_dict):
    """
    Extract arguments for a dataclass from the flattened args_dict,
    handling nested dataclasses recursively.

    Args:
        cls: The dataclass to extract args for
        prefix: The prefix used for this dataclass's arguments
        args_dict: Flat dictionary of all parsed arguments

    Returns:
        dict: Arguments for creating an instance of cls
    """
    class_args = {}
    type_hints = get_type_hints(cls)

    for field in fields(cls):
        field_type = type_hints.get(field.name, field.type)

        # Check if this field is a nested dataclass
        if _is_dataclass_type(field_type):
            nested_cls = _get_dataclass_type(field_type)
            nested_prefix = f"{prefix}{field.name}_"

            # Recursively extract nested dataclass args
            nested_args = _extract_dataclass_args(nested_cls, nested_prefix, args_dict)

            # Only create nested instance if we have at least some args
            if nested_args:
                try:
                    class_args[field.name] = nested_cls(**nested_args)
                except TypeError:
                    # If we can't create the nested instance, skip it
                    pass
        else:
            # Standard field - look for it in args_dict
            arg_name = f"{prefix}{field.name}".replace("-", "_")
            if arg_name in args_dict:
                class_args[field.name] = args_dict[arg_name]

    return class_args


def create_config_hierarchy(
    *dataclass_configs: Union[Any, Tuple[Any, Dict[str, Any]]],
    **kwargs: Any,
) -> Tuple[
    argparse.ArgumentParser,
    Callable[[Optional[List[str]]], Optional[Dict[str, Any]]],
]:
    """
    Convenience function to create a complete configuration system with config
        file support.

    Returns a configured parser and a parse function with built-in config
        management.
    """
    parser_configs = compose_dataclass_argparse(*dataclass_configs, **kwargs)

    def parse(args=None):
        return parse_with_config_management(parser_configs, args)

    return parser_configs[0], parse


def create_simple_config_hierarchy(
    *dataclass_configs: Union[Any, Tuple[Any, Dict[str, Any]]],
    **kwargs: Any,
) -> Tuple[argparse.ArgumentParser, Callable[[Optional[List[str]]], Dict[str, Any]]]:
    """
    Create a configuration system without built-in config file management
        options.
    Use this if you want to handle config files manually.
    """
    kwargs["add_config_options"] = False
    parser_configs = compose_dataclass_argparse(*dataclass_configs, **kwargs)

    def parse(args=None):
        return parse_composed_args(parser_configs, args)

    return parser_configs[0], parse
