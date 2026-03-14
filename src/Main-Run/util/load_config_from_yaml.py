import logging
from pathlib import Path
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

def load_config_from_yaml(script_path: Path):
    def decorator(cls):
        try:
            script_dir = script_path.parent
            config_path = script_dir / 'config.yaml'
            default_config_path = script_dir / 'config.default.yaml'
            
            update_config(config_path, default_config_path)

            if config_path.exists():
                logging.info(f"Loading config from: {config_path}")
                yaml = YAML()
                with open(config_path, 'r', encoding='utf-8') as f:
                    nested_config = yaml.load(f) or {}

                for section_name, section_data in nested_config.items():
                    if isinstance(section_data, dict):
                        for key, value in section_data.items():
                            if hasattr(cls, key):
                                setattr(cls, key, value) 
                            else:
                                logging.warning(f"Skipping key '{key}' from YAML section '{section_name}'")
            else:
                logging.warning(f"Config file {config_path} not found. Using hardcoded defaults for {cls.__name__}.")

        except Exception as e:
            logging.error(f"Error applying config loader decorator to {cls.__name__}: {e}", exc_info=True)

        logging.info(f"--- Finished applying decorator to {cls.__name__} ---")
        return cls
    return decorator

def update_config(config_path, default_config_path):
    """
    Update the config file to match the structure and version of the default config file,
    while preserving comments, field order, and formatting.

    Args:
        config_path (str or Path): Path to the current config.yaml file.
        default_config_path (str or Path): Path to the default config.default.yaml file.
    """
    config_path = Path(config_path)
    default_config_path = Path(default_config_path)

    yaml = YAML()
    yaml.preserve_quotes = True  # Preserve quotes in YAML

    # Load the default config
    with open(default_config_path, 'r', encoding='utf-8') as default_file:
        default_config = yaml.load(default_file)

    # Load the current config if it exists, otherwise start with an empty CommentedMap
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as config_file:
            current_config = yaml.load(config_file) or CommentedMap()
    else:
        current_config = CommentedMap()

    # Update the current config with missing fields from the default config
    def recursive_update(current, default):
        for key, value in default.items():
            if isinstance(value, dict):
                current[key] = recursive_update(current.get(key, CommentedMap()), value)
            elif isinstance(value, list):
                if key not in current:
                    current[key] = CommentedSeq(value)
                else:
                    current[key] = CommentedSeq(current[key])
            else:
                if key not in current:
                    current[key] = value
        return current

    updated_config = recursive_update(current_config, default_config)

    # Ensure the order of fields matches the default config
    final_config = CommentedMap()
    for key in default_config:
        final_config[key] = updated_config.pop(key, default_config[key])
    # Add any remaining keys that were not in the default config
    for key, value in updated_config.items():
        final_config[key] = value

    # Write the updated config back to the file, preserving comments, order, and formatting
    with open(config_path, 'w', encoding='utf-8') as config_file:
        yaml.dump(final_config, config_file)

    logging.info(f"Config file '{config_path}' updated to version {final_config['version']}.")