"""
Validation utilities for CLI inputs and configuration.
"""

import re
from pathlib import Path
from typing import Optional, List, Tuple

from codewiki.cli.utils.errors import ConfigurationError, RepositoryError


def validate_output_directory(path: str) -> Path:
    """
    Validate output directory path.
    
    Args:
        path: Directory path to validate
        
    Returns:
        Validated Path object
        
    Raises:
        ConfigurationError: If path is invalid
    """
    if not path or not path.strip():
        raise ConfigurationError("Output directory cannot be empty")
    
    try:
        resolved_path = Path(path).expanduser().resolve()
        
        # Check if path is writable (or parent is writable if path doesn't exist)
        if resolved_path.exists():
            if not resolved_path.is_dir():
                raise ConfigurationError(
                    f"Output path exists but is not a directory: {path}"
                )
        
        return resolved_path
    except Exception as e:
        raise ConfigurationError(f"Invalid output directory path: {path}\nError: {e}")


def validate_repository_path(path: Path) -> Path:
    """
    Validate repository path exists and contains code files.
    
    Args:
        path: Repository path to validate
        
    Returns:
        Validated Path object
        
    Raises:
        RepositoryError: If repository is invalid
    """
    path = Path(path).expanduser().resolve()
    
    if not path.exists():
        raise RepositoryError(f"Repository path does not exist: {path}")
    
    if not path.is_dir():
        raise RepositoryError(f"Repository path is not a directory: {path}")
    
    return path


def detect_supported_languages(directory: Path) -> List[Tuple[str, int]]:
    """
    Detect supported programming languages in a directory.
    
    Args:
        directory: Directory to scan
        
    Returns:
        List of (language, file_count) tuples
    """
    language_extensions = {
        'Python': ['.py'],
        'Java': ['.java'],
        'JavaScript': ['.js', '.jsx'],
        'TypeScript': ['.ts', '.tsx'],
        'C': ['.c', '.h'],
        'C++': ['.cpp', '.hpp', '.cc', '.hh', '.cxx', '.hxx'],
        'C#': ['.cs'],
        'PHP': ['.php', '.phtml', '.inc'],
        'Kotlin': ['.kt', '.kts'],
    }
    
    # Directories to exclude from counting
    excluded_dirs = {
        'node_modules', '__pycache__', '.git', 'build', 'dist', 
        '.venv', 'venv', 'env', '.env', 'target', 'bin', 'obj',
        '.pytest_cache', '.mypy_cache', '.tox', 'coverage',
        'htmlcov', '.eggs', '*.egg-info', 'vendor', 'bower_components',
        '.idea', '.vscode', '.gradle', '.mvn'
    }
    
    def should_exclude_file(file_path: Path) -> bool:
        """Check if file is in an excluded directory."""
        parts = file_path.parts
        return any(excluded_dir in parts for excluded_dir in excluded_dirs)
    
    language_counts = {}
    
    for language, extensions in language_extensions.items():
        count = 0
        for ext in extensions:
            # Filter out files in excluded directories
            count += sum(
                1 for f in directory.rglob(f"*{ext}")
                if f.is_file() and not should_exclude_file(f)
            )
        
        if count > 0:
            language_counts[language] = count
    
    # Sort by count descending
    return sorted(language_counts.items(), key=lambda x: x[1], reverse=True)

