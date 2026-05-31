"""
Configuration commands for CodeWiki CLI.
"""

import json
import sys
import click
from typing import Optional, List

from codewiki.cli.config_manager import ConfigManager
from codewiki.cli.models.config import AgentInstructions
from codewiki.cli.utils.errors import (
    ConfigurationError, 
    handle_error, 
    EXIT_SUCCESS,
    EXIT_CONFIG_ERROR
)

def parse_patterns(patterns_str: str) -> List[str]:
    """Parse comma-separated patterns into a list."""
    if not patterns_str:
        return []
    return [p.strip() for p in patterns_str.split(',') if p.strip()]


@click.group(name="config")
def config_group():
    """Manage CodeWiki configuration."""
    pass


@config_group.command(name="set")
@click.option(
    "--main-model",
    type=str,
    help="Optional model label stored in task metadata"
)
@click.option(
    "--cluster-model",
    type=str,
    help="Optional model label stored in clustering task metadata"
)
@click.option(
    "--max-tokens",
    type=int,
    help="Maximum tokens for LLM response (default: 32768)"
)
@click.option(
    "--max-token-per-module",
    type=int,
    help="Maximum tokens per module for clustering (default: 36369)"
)
@click.option(
    "--max-token-per-leaf-module",
    type=int,
    help="Maximum tokens per leaf module (default: 16000)"
)
@click.option(
    "--max-depth",
    type=int,
    help="Maximum depth for hierarchical decomposition (default: 2)"
)
@click.option(
    "--provider",
    type=click.Choice(
        ['ide-bridge'],
        case_sensitive=False,
    ),
    help="LLM provider type. This build supports only 'ide-bridge'.",
)
def config_set(
    main_model: Optional[str],
    cluster_model: Optional[str],
    max_tokens: Optional[int],
    max_token_per_module: Optional[int],
    max_token_per_leaf_module: Optional[int],
    max_depth: Optional[int],
    provider: Optional[str] = None,
):
    """
    Set configuration values for CodeWiki.
    
    Examples:

    \b
    # IDE Bridge mode - no API key needed; prompts are written to task files
    $ codewiki config set --provider ide-bridge

    \b
    # Set max tokens for LLM response
    $ codewiki config set --max-tokens 16384

    \b
    # Set all max token settings
    $ codewiki config set --max-tokens 32768 --max-token-per-module 40000 --max-token-per-leaf-module 20000

    \b
    # Set max depth for hierarchical decomposition
    $ codewiki config set --max-depth 3
    """
    try:
        # Check if at least one option is provided
        if not any([
            main_model,
            cluster_model,
            max_tokens,
            max_token_per_module,
            max_token_per_leaf_module,
            max_depth,
            provider,
        ]):
            click.echo("No options provided. Use --help for usage information.")
            sys.exit(EXIT_CONFIG_ERROR)
        
        # Validate inputs before saving
        validated_data = {}
        
        if main_model:
            validated_data['main_model'] = main_model

        if cluster_model:
            validated_data['cluster_model'] = cluster_model
        
        if max_tokens is not None:
            if max_tokens < 1:
                raise ConfigurationError("max_tokens must be a positive integer")
            validated_data['max_tokens'] = max_tokens
        
        if max_token_per_module is not None:
            if max_token_per_module < 1:
                raise ConfigurationError("max_token_per_module must be a positive integer")
            validated_data['max_token_per_module'] = max_token_per_module
        
        if max_token_per_leaf_module is not None:
            if max_token_per_leaf_module < 1:
                raise ConfigurationError("max_token_per_leaf_module must be a positive integer")
            validated_data['max_token_per_leaf_module'] = max_token_per_leaf_module
        
        if max_depth is not None:
            if max_depth < 1:
                raise ConfigurationError("max_depth must be a positive integer")
            validated_data['max_depth'] = max_depth

        if provider is not None:
            validated_data['provider'] = provider

        # Create config manager and save
        manager = ConfigManager()
        manager.load()  # Load existing config if present

        manager.save(
            main_model=validated_data.get('main_model'),
            cluster_model=validated_data.get('cluster_model'),
            max_tokens=validated_data.get('max_tokens'),
            max_token_per_module=validated_data.get('max_token_per_module'),
            max_token_per_leaf_module=validated_data.get('max_token_per_leaf_module'),
            max_depth=validated_data.get('max_depth'),
            provider=validated_data.get('provider'),
        )
        
        # Display success messages
        click.echo()
        if main_model:
            click.secho(f"OK Main model: {main_model}", fg="green")
        
        if cluster_model:
            click.secho(f"OK Cluster model: {cluster_model}", fg="green")
            
        if max_tokens:
            click.secho(f"OK Max tokens: {max_tokens}", fg="green")
        
        if max_token_per_module:
            click.secho(f"OK Max token per module: {max_token_per_module}", fg="green")
        
        if max_token_per_leaf_module:
            click.secho(f"OK Max token per leaf module: {max_token_per_leaf_module}", fg="green")
        
        if max_depth:
            click.secho(f"OK Max depth: {max_depth}", fg="green")

        if provider:
            click.secho(f"OK Provider: {provider}", fg="green")

        click.echo("\n" + click.style("Configuration updated successfully.", fg="green", bold=True))
        
    except ConfigurationError as e:
        click.secho(f"\nERROR Configuration error: {e.message}", fg="red", err=True)
        sys.exit(e.exit_code)
    except Exception as e:
        sys.exit(handle_error(e))


@config_group.command(name="show")
@click.option(
    "--json",
    "output_json",
    is_flag=True,
    help="Output in JSON format"
)
def config_show(output_json: bool):
    """
    Display current configuration.

    Examples:
    
    \b
    # Display configuration
    $ codewiki config show
    
    \b
    # Display as JSON
    $ codewiki config show --json
    """
    try:
        manager = ConfigManager()
        
        if not manager.load():
            click.secho("\nERROR Configuration not found.", fg="red", err=True)
            click.echo("\nPlease run 'codewiki config set --provider ide-bridge'.")
            click.echo("\nFor more help: codewiki config set --help")
            sys.exit(EXIT_CONFIG_ERROR)
        
        config = manager.get_config()
        
        if output_json:
            # JSON output
            output = {
                "provider": config.provider if config else "ide-bridge",
                "main_model": config.main_model if config else "",
                "cluster_model": config.cluster_model if config else "",
                "default_output": config.default_output if config else "docs",
                "max_tokens": config.max_tokens if config else 32768,
                "max_token_per_module": config.max_token_per_module if config else 36369,
                "max_token_per_leaf_module": config.max_token_per_leaf_module if config else 16000,
                "max_depth": config.max_depth if config else 2,
                "agent_instructions": config.agent_instructions.to_dict() if config and config.agent_instructions else {},
                "config_file": str(manager.config_file_path)
            }
            click.echo(json.dumps(output, indent=2))
        else:
            # Human-readable output
            click.echo()
            click.secho("CodeWiki Configuration", fg="blue", bold=True)
            click.echo("-" * 40)
            click.echo()
            
            click.secho("Credentials", fg="cyan", bold=True)
            click.secho(
                "  IDE Bridge mode: no API key needed; complete generated task files in your AI IDE",
                fg="cyan",
            )

            click.echo()
            click.secho("Bridge Settings", fg="cyan", bold=True)
            if config:
                click.echo(f"  Provider:         {config.provider}")
                click.echo(f"  Main Model:       {config.main_model or 'Not set'}")
                click.echo(f"  Cluster Model:    {config.cluster_model or 'Not set'}")
                click.echo("  Bridge Tasks:     <output>/.codewiki/ide_bridge/tasks")
                click.echo("  Bridge Results:   <output>/.codewiki/ide_bridge/results")
            else:
                click.secho("  Not configured", fg="yellow")
            
            click.echo()
            click.secho("Output Settings", fg="cyan", bold=True)
            if config:
                click.echo(f"  Default Output:   {config.default_output}")
            
            click.echo()
            click.secho("Token Settings", fg="cyan", bold=True)
            if config:
                click.echo(f"  Max Tokens:              {config.max_tokens}")
                click.echo(f"  Max Token/Module:        {config.max_token_per_module}")
                click.echo(f"  Max Token/Leaf Module:   {config.max_token_per_leaf_module}")
            
            click.echo()
            click.secho("Decomposition Settings", fg="cyan", bold=True)
            if config:
                click.echo(f"  Max Depth:               {config.max_depth}")
            
            click.echo()
            click.secho("Agent Instructions", fg="cyan", bold=True)
            if config and config.agent_instructions and not config.agent_instructions.is_empty():
                agent = config.agent_instructions
                if agent.include_patterns:
                    click.echo(f"  Include patterns:   {', '.join(agent.include_patterns)}")
                if agent.exclude_patterns:
                    click.echo(f"  Exclude patterns:   {', '.join(agent.exclude_patterns)}")
                if agent.focus_modules:
                    click.echo(f"  Focus modules:      {', '.join(agent.focus_modules)}")
                if agent.doc_type:
                    click.echo(f"  Doc type:           {agent.doc_type}")
                if agent.custom_instructions:
                    click.echo(f"  Custom instructions: {agent.custom_instructions[:50]}...")
            else:
                click.secho("  Using defaults (no custom settings)", fg="yellow")
            
            click.echo()
            click.echo(f"Configuration file: {manager.config_file_path}")
            click.echo()
        
    except Exception as e:
        sys.exit(handle_error(e))


@config_group.command(name="validate")
@click.option(
    "--quick",
    is_flag=True,
    help="Kept for compatibility; validation is local-only in IDE Bridge mode"
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Show detailed validation steps"
)
def config_validate(quick: bool, verbose: bool):
    """
    Validate IDE Bridge configuration.
    
    Checks:
      - Configuration file exists and is valid
      - IDE Bridge provider is selected
      - Task/result file workflow is available
    
    Examples:
    
    \b
    # Full validation
    $ codewiki config validate
    
    \b
    # Quick validation (config only)
    $ codewiki config validate --quick
    
    \b
    # Verbose output
    $ codewiki config validate --verbose
    """
    try:
        click.echo()
        click.secho("Validating configuration...", fg="blue", bold=True)
        click.echo()
        
        manager = ConfigManager()
        
        # Step 1: Check config file
        if verbose:
            click.echo("[1/3] Checking configuration file...")
            click.echo(f"      Path: {manager.config_file_path}")
        
        if not manager.load():
            click.secho("ERROR Configuration file not found", fg="red")
            click.echo()
            click.echo("Error: Configuration is incomplete. Run 'codewiki config set --help' for setup instructions.")
            sys.exit(EXIT_CONFIG_ERROR)
        
        if verbose:
            click.secho("      OK File exists", fg="green")
            click.secho("      OK Valid JSON format", fg="green")
        else:
            click.secho("OK Configuration file exists", fg="green")
        
        config = manager.get_config()
        if not config or config.provider != "ide-bridge":
            click.secho("ERROR Unsupported provider. Use: codewiki config set --provider ide-bridge", fg="red")
            sys.exit(EXIT_CONFIG_ERROR)

        # Step 2: Check provider
        if verbose:
            click.echo()
            click.echo("[2/3] Checking provider...")
            click.secho("      OK Provider: ide-bridge", fg="green")
        else:
            click.secho("OK Provider: ide-bridge", fg="green")

        # Step 3: Check IDE Bridge mode
        if verbose:
            click.echo()
            click.echo("[3/3] Checking IDE Bridge mode...")
            click.secho("      OK API key not required", fg="green")
            click.secho("      OK Base URL not required", fg="green")
            click.secho("      OK Model configuration not required", fg="green")
            click.secho("      OK Tasks will be written under <output>/.codewiki/ide_bridge/tasks", fg="green")
            click.secho("      -> Complete each task in your AI IDE and save results under the matching results path.", fg="cyan")
        else:
            click.secho("OK IDE Bridge mode ready", fg="green")
        
        # Success
        click.echo()
        click.secho("OK Configuration is valid!", fg="green", bold=True)
        click.echo()
        
    except ConfigurationError as e:
        click.secho(f"\nERROR Configuration error: {e.message}", fg="red", err=True)
        sys.exit(e.exit_code)
    except Exception as e:
        sys.exit(handle_error(e, verbose=verbose))


@config_group.command(name="agent")
@click.option(
    "--include",
    "-i",
    type=str,
    default=None,
    help="Comma-separated file patterns to include (e.g., '*.cs,*.py')",
)
@click.option(
    "--exclude",
    "-e",
    type=str,
    default=None,
    help="Comma-separated patterns to exclude (e.g., '*Tests*,*Specs*')",
)
@click.option(
    "--focus",
    "-f",
    type=str,
    default=None,
    help="Comma-separated modules/paths to focus on (e.g., 'src/core,src/api')",
)
@click.option(
    "--doc-type",
    "-t",
    type=click.Choice(['api', 'architecture', 'user-guide', 'developer'], case_sensitive=False),
    default=None,
    help="Default type of documentation to generate",
)
@click.option(
    "--instructions",
    type=str,
    default=None,
    help="Custom instructions for the documentation agent",
)
@click.option(
    "--clear",
    is_flag=True,
    help="Clear all agent instructions",
)
def config_agent(
    include: Optional[str],
    exclude: Optional[str],
    focus: Optional[str],
    doc_type: Optional[str],
    instructions: Optional[str],
    clear: bool
):
    """
    Configure default agent instructions for documentation generation.
    
    These settings are used as defaults when running 'codewiki generate'.
    Runtime options (--include, --exclude, etc.) override these defaults.
    
    Examples:
    
    \b
    # Set include patterns for C# projects
    $ codewiki config agent --include "*.cs"
    
    \b
    # Exclude test projects
    $ codewiki config agent --exclude "*Tests*,*Specs*,test_*"
    
    \b
    # Focus on specific modules
    $ codewiki config agent --focus "src/core,src/api"
    
    \b
    # Set default doc type
    $ codewiki config agent --doc-type architecture
    
    \b
    # Add custom instructions
    $ codewiki config agent --instructions "Focus on public APIs and include usage examples"
    
    \b
    # Clear all agent instructions
    $ codewiki config agent --clear
    """
    try:
        manager = ConfigManager()
        
        if not manager.load():
            click.secho("\nERROR Configuration not found.", fg="red", err=True)
            click.echo("\nPlease run 'codewiki config set --provider ide-bridge' first.")
            sys.exit(EXIT_CONFIG_ERROR)
        
        config = manager.get_config()
        
        if clear:
            # Clear all agent instructions
            config.agent_instructions = AgentInstructions()
            manager.save()
            click.echo()
            click.secho("OK Agent instructions cleared", fg="green")
            click.echo()
            return
        
        # Check if at least one option is provided
        if not any([include, exclude, focus, doc_type, instructions]):
            # Display current settings
            click.echo()
            click.secho("Agent Instructions", fg="blue", bold=True)
            click.echo("-" * 40)
            click.echo()
            
            agent = config.agent_instructions
            if agent and not agent.is_empty():
                if agent.include_patterns:
                    click.echo(f"  Include patterns:   {', '.join(agent.include_patterns)}")
                if agent.exclude_patterns:
                    click.echo(f"  Exclude patterns:   {', '.join(agent.exclude_patterns)}")
                if agent.focus_modules:
                    click.echo(f"  Focus modules:      {', '.join(agent.focus_modules)}")
                if agent.doc_type:
                    click.echo(f"  Doc type:           {agent.doc_type}")
                if agent.custom_instructions:
                    click.echo(f"  Custom instructions: {agent.custom_instructions}")
            else:
                click.secho("  No agent instructions configured (using defaults)", fg="yellow")
            
            click.echo()
            click.echo("Use 'codewiki config agent --help' for usage information.")
            click.echo()
            return
        
        # Update agent instructions
        current = config.agent_instructions or AgentInstructions()
        
        if include is not None:
            current.include_patterns = parse_patterns(include) if include else None
        if exclude is not None:
            current.exclude_patterns = parse_patterns(exclude) if exclude else None
        if focus is not None:
            current.focus_modules = parse_patterns(focus) if focus else None
        if doc_type is not None:
            current.doc_type = doc_type if doc_type else None
        if instructions is not None:
            current.custom_instructions = instructions if instructions else None
        
        config.agent_instructions = current
        manager.save()
        
        # Display success messages
        click.echo()
        if include:
            click.secho(f"OK Include patterns: {parse_patterns(include)}", fg="green")
        if exclude:
            click.secho(f"OK Exclude patterns: {parse_patterns(exclude)}", fg="green")
        if focus:
            click.secho(f"OK Focus modules: {parse_patterns(focus)}", fg="green")
        if doc_type:
            click.secho(f"OK Doc type: {doc_type}", fg="green")
        if instructions:
            click.secho(f"OK Custom instructions set", fg="green")
        
        click.echo("\n" + click.style("Agent instructions updated successfully.", fg="green", bold=True))
        click.echo()
        
    except ConfigurationError as e:
        click.secho(f"\nERROR Configuration error: {e.message}", fg="red", err=True)
        sys.exit(e.exit_code)
    except Exception as e:
        sys.exit(handle_error(e))
