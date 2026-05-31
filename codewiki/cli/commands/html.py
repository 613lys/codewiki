"""Generate an HTML viewer from existing CodeWiki markdown output."""

from pathlib import Path

import click

from codewiki.cli.html_generator import HTMLGenerator
from codewiki.cli.utils.errors import FileSystemError, handle_error
from codewiki.cli.utils.logging import create_logger


@click.command(name="html")
@click.option(
    "--docs-dir",
    "docs_dir",
    default="./docs",
    show_default=True,
    type=click.Path(path_type=Path),
    help="Existing CodeWiki documentation directory containing markdown files.",
)
@click.option(
    "--output",
    "output_path",
    default=None,
    type=click.Path(path_type=Path),
    help="Output HTML path. Defaults to <docs-dir>/index.html.",
)
@click.option(
    "--title",
    default=None,
    help="Viewer title. Defaults to the documentation directory name.",
)
@click.option(
    "--verbose",
    is_flag=True,
    help="Enable verbose output.",
)
def html_command(
    docs_dir: Path,
    output_path: Path | None,
    title: str | None,
    verbose: bool,
):
    """Create index.html from an existing CodeWiki markdown directory."""
    logger = create_logger(verbose)

    try:
        docs_dir = docs_dir.resolve()
        if not docs_dir.exists() or not docs_dir.is_dir():
            raise FileSystemError(f"Documentation directory not found: {docs_dir}")

        markdown_files = sorted(docs_dir.glob("*.md"))
        if not markdown_files:
            raise FileSystemError(f"No markdown files found in: {docs_dir}")

        if output_path is None:
            output_path = docs_dir / "index.html"
        else:
            output_path = output_path.resolve()

        if title is None:
            title = f"{docs_dir.name} Documentation"

        generator = HTMLGenerator()
        module_tree = generator.load_module_tree(docs_dir)
        metadata = generator.load_metadata(docs_dir)
        generator.generate(
            output_path=output_path,
            title=title,
            module_tree=module_tree,
            docs_dir=docs_dir,
            metadata=metadata,
        )

        logger.success("HTML viewer generated")
        click.echo(f"Output: {output_path}")
        click.echo(f"Embedded markdown files: {len(markdown_files)}")

    except Exception as error:
        raise click.exceptions.Exit(handle_error(error, verbose))
