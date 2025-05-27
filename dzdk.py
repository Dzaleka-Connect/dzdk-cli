import os
import click
import requests
import json
import csv
from typing import Optional, Dict, Any, List
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeRemainingColumn
from rich.panel import Panel
from rich.layout import Layout
from rich.text import Text
from rich.box import ROUNDED
from rich.style import Style
from rich.theme import Theme
from datetime import datetime
import sys
from pathlib import Path
import yaml
import concurrent.futures
from urllib.parse import urljoin
import pandas as pd
from tabulate import tabulate
import cmd
import readline
import rlcompleter
import atexit
import glob
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import WordCompleter
import time

# Initialize console with custom theme
custom_theme = Theme({
    "info": "cyan",
    "warning": "yellow",
    "danger": "red",
    "success": "green",
    "title": "bold cyan",
    "subtitle": "bold green",
    "highlight": "bold yellow",
    "dim": "dim",
})
console = Console(theme=custom_theme)

# UI Helper Functions
def create_header(title: str, subtitle: str = None) -> Panel:
    """Create a styled header panel."""
    header = Text(title, style="title")
    if subtitle:
        header.append("\n" + subtitle, style="subtitle")
    return Panel(header, border_style="cyan", box=ROUNDED)

def create_info_panel(title: str, content: str) -> Panel:
    """Create a styled information panel."""
    return Panel(
        content,
        title=title,
        border_style="green",
        box=ROUNDED,
        padding=(1, 2)
    )

def create_table(title: str, columns: List[Dict[str, str]]) -> Table:
    """Create a styled table with consistent formatting."""
    table = Table(
        title=title,
        box=ROUNDED,
        title_style="title",
        header_style="highlight",
        border_style="cyan",
        show_lines=True,
        padding=(0, 1)
    )
    for col in columns:
        table.add_column(col["name"], style=col["style"])
    return table

# Configuration
CONFIG_DIR = Path(os.environ.get('DZDK_CONFIG_DIR', str(Path.home() / '.config' / 'dzdk')))
CONFIG_FILE = CONFIG_DIR / 'config.yaml'
DEFAULT_CONFIG = {
    'api_url': 'https://services.dzaleka.com/api',
    'timeout': 30
}

# API Endpoints to check
API_ENDPOINTS = {
    'services': '/services',
    'events': '/events',
    'photos': '/photos',
    'population': '/population',
    'resources': '/resources'
}

def load_config() -> Dict[str, Any]:
    """Load configuration from file or create default."""
    if not CONFIG_DIR.exists():
        CONFIG_DIR.mkdir(parents=True)
    
    if not CONFIG_FILE.exists():
        with open(CONFIG_FILE, 'w') as f:
            yaml.dump(DEFAULT_CONFIG, f)
        return DEFAULT_CONFIG
    
    with open(CONFIG_FILE) as f:
        config = yaml.safe_load(f)
        
        # Ensure API URL is properly formatted
        if 'api_url' in config:
            api_url = config['api_url']
            if not api_url.startswith('http'):
                api_url = f"https://{api_url}"
            if not api_url.endswith('/api'):
                api_url = api_url.rstrip('/') + '/api'
            config['api_url'] = api_url
            
        return config

def save_config(config: Dict[str, Any]) -> None:
    """Save configuration to file."""
    with open(CONFIG_FILE, 'w') as f:
        yaml.dump(config, f)

# Load configuration
config = load_config()
BASE_URL = config['api_url']
TIMEOUT = config['timeout']

def format_response(response: requests.Response) -> Dict[str, Any]:
    """Format API response with proper error handling."""
    try:
        response.raise_for_status()
        try:
            return response.json()
        except json.JSONDecodeError:
            # Clean output for HTML/web page response
            url = response.url
            console.print(create_info_panel(
                "Web Page Detected",
                f"[warning]The endpoint returned a web page, not an API resource.[/warning]\n\n"
                f"[info]You can view this in your browser:[/info]\n"
                f"[cyan]{url}[/cyan]"
            ))
            return {
                'status': 'error',
                'message': 'Endpoint returned HTML instead of JSON'
            }
    except requests.exceptions.HTTPError as e:
        console.print(f"[red]HTTP Error: {str(e)}[/red]")
        sys.exit(1)
    except requests.exceptions.RequestException as e:
        console.print(f"[red]Request Error: {str(e)}[/red]")
        sys.exit(1)

def check_api_health() -> bool:
    """Check if the API is healthy and accessible."""
    try:
        response = requests.get(f"{BASE_URL}/health", timeout=TIMEOUT)
        # Consider any 2xx response as healthy
        return 200 <= response.status_code < 300
    except requests.exceptions.RequestException:
        return False

def check_endpoint(endpoint: str) -> Dict[str, Any]:
    """Check a single API endpoint."""
    url = urljoin(BASE_URL, endpoint)
    try:
        start_time = datetime.now()
        response = requests.get(url, timeout=TIMEOUT)
        end_time = datetime.now()
        response_time = (end_time - start_time).total_seconds()
        
        # Get status code
        status_code = response.status_code
        
        # Try to parse JSON response
        try:
            response.json()
            response_type = "JSON"
            status = "OK"
        except json.JSONDecodeError:
            response_type = "HTML"
            # Consider HTML responses with 2xx status codes as healthy
            status = "OK" if 200 <= status_code < 300 else f"Error: {status_code}"
        
        return {
            'endpoint': endpoint,
            'status': status,
            'response_time': response_time,
            'response_type': response_type,
            'error': None
        }
    except requests.exceptions.RequestException as e:
        return {
            'endpoint': endpoint,
            'status': "Error",
            'response_time': None,
            'response_type': None,
            'error': str(e)
        }

def check_all_endpoints() -> List[Dict[str, Any]]:
    """Check all API endpoints concurrently."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        future_to_endpoint = {
            executor.submit(check_endpoint, endpoint): endpoint 
            for endpoint in API_ENDPOINTS.values()
        }
        results = []
        for future in concurrent.futures.as_completed(future_to_endpoint):
            results.append(future.result())
    return results

def display_welcome():
    """Display a welcome message with basic usage information."""
    welcome_text = """
✨ [title]Welcome to Dzaleka Digital Heritage CLI[/title]

[subtitle]Your gateway to the Dzaleka Refugee Camp's digital resources[/subtitle]

[highlight]Available Commands:[/highlight]

[cyan]Health Check[/cyan]
• [dim]dzdk health[/dim] - Check the health of all API endpoints

[cyan]Services Management[/cyan]
• [dim]dzdk services list[/dim] - List all available services (12 per page)
• [dim]dzdk services list --page 2[/dim] - View second page of services
• [dim]dzdk services list --search <query>[/dim] - Search services
• [dim]dzdk services list --category <category>[/dim] - Filter by category
• [dim]dzdk services list --status <status>[/dim] - Filter by status
• [dim]dzdk services list --sort-by <field> --sort-order <order>[/dim] - Sort results
• [dim]dzdk services get --id <id>[/dim] - Get details for a specific service

[cyan]Event Management[/cyan]
• [dim]dzdk events list[/dim] - List all events (12 per page)
• [dim]dzdk events list --page 2[/dim] - View second page of events
• [dim]dzdk events list --search <query>[/dim] - Search events
• [dim]dzdk events list --category <category>[/dim] - Filter by category
• [dim]dzdk events get --id <id>[/dim] - Get details for a specific event

[cyan]Photo Management[/cyan]
• [dim]dzdk photos list[/dim] - List all available photos (12 per page)
• [dim]dzdk photos list --page 2[/dim] - View second page of photos
• [dim]dzdk photos list --search <query>[/dim] - Search photos
• [dim]dzdk photos list --category <category>[/dim] - Filter by category
• [dim]dzdk photos get --id <id>[/dim] - Get details for a specific photo
• [dim]dzdk photos upload --file <path> --title <title>[/dim] - Upload a photo
• [dim]dzdk photos metadata --id <id>[/dim] - View photo metadata
• [dim]dzdk photos edit --id <id> [options][/dim] - Edit photo information

[cyan]Resource Management[/cyan]
• [dim]dzdk resources list[/dim] - List all available resources (12 per page)
• [dim]dzdk resources list --page 2[/dim] - View second page of resources
• [dim]dzdk resources list --search <query>[/dim] - Search resources
• [dim]dzdk resources list --category <category>[/dim] - Filter by category
• [dim]dzdk resources get --id <id>[/dim] - Get details for a specific resource
• [dim]dzdk resources fetch --id <id> --output <file>[/dim] - Download a resource

[cyan]Statistics and Analytics[/cyan]
• [dim]dzdk stats services[/dim] - Show service distribution and statistics
• [dim]dzdk stats services --output <file>[/dim] - Generate service statistics report
• [dim]dzdk stats usage[/dim] - Show usage statistics and trends
• [dim]dzdk stats usage --days <days> --output <file>[/dim] - Generate usage report

[cyan]Configuration[/cyan]
• [dim]dzdk show_config[/dim] - Show current configuration
• [dim]dzdk config --interactive[/dim] - Interactive configuration mode
• [dim]dzdk config --url <url>[/dim] - Set API URL
• [dim]dzdk config --timeout <seconds>[/dim] - Set request timeout

[cyan]Search[/cyan]
• [dim]dzdk search --query <query> [--type <type>][/dim] - Search across resources

[cyan]Batch Operations[/cyan]
• [dim]dzdk batch download --type <type> --ids <ids>[/dim] - Download multiple items
• [dim]dzdk batch upload --directory <dir> --type <type>[/dim] - Upload multiple files

[cyan]Export[/cyan]
• [dim]dzdk export csv --type <type> --output <file>[/dim] - Export data to CSV
• [dim]dzdk export report --type <type> --output <file>[/dim] - Generate detailed report

[cyan]Interactive Shell[/cyan]
• [dim]dzdk shell[/dim] - Start interactive shell mode

[highlight]Need Help?[/highlight]
• Use [cyan]--help[/cyan] with any command for detailed information
• Example: [cyan]dzdk services list --help[/cyan]

[dim]For more information, visit: https://services.dzaleka.com[/dim]
    """
    console.print(Panel(
        welcome_text,
        border_style="cyan",
        box=ROUNDED,
        padding=(1, 2),
        title="[bold cyan]DZDK CLI[/bold cyan]",
        subtitle="[dim]v0.1.0[/dim]"
    ))

@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx):
    """dzdk - Dzaleka Digital Heritage CLI
    
    A command-line interface for interacting with the Dzaleka Digital Heritage API.
    """
    if ctx.invoked_subcommand is None:
        display_welcome()
        # Show help text after welcome message
        click.echo("\n")
        click.echo(ctx.get_help())

@cli.command()
@click.option('--url', help='API base URL')
@click.option('--timeout', type=int, help='Request timeout in seconds')
@click.option('--interactive', is_flag=True, help='Start interactive configuration mode')
def config_command(url: Optional[str], timeout: Optional[int], interactive: bool):
    """Configure CLI settings"""
    if interactive:
        console.print(create_header("Interactive Configuration", "Configure your CLI settings"))
        
        # Show current configuration
        current_config = load_config()
        console.print(create_info_panel(
            "Current Configuration",
            f"API URL: {current_config['api_url']}\n"
            f"Timeout: {current_config['timeout']} seconds"
        ))
        
        # Get new API URL
        new_url = click.prompt(
            "Enter API URL",
            default=current_config['api_url'],
            show_default=True
        )
        if not new_url.endswith('/api'):
            new_url = new_url.rstrip('/') + '/api'
        
        # Get new timeout
        new_timeout = click.prompt(
            "Enter timeout in seconds",
            default=current_config['timeout'],
            type=int,
            show_default=True
        )
        
        # Update configuration
        config['api_url'] = new_url
        config['timeout'] = new_timeout
        save_config(config)
        
        console.print(create_info_panel(
            "Configuration Updated",
            f"""
[success]Configuration has been updated successfully![/success]

[highlight]New Settings:[/highlight]
API URL: {new_url}
Timeout: {new_timeout} seconds
            """
        ))
        return
    
    if url:
        # Ensure URL ends with /api
        if not url.endswith('/api'):
            url = url.rstrip('/') + '/api'
        config['api_url'] = url
    if timeout:
        config['timeout'] = timeout
    
    save_config(config)
    console.print("[green]Configuration updated successfully[/green]")
    console.print(f"[info]API URL: {config['api_url']}[/info]")
    console.print(f"[info]Timeout: {config['timeout']} seconds[/info]")

@cli.command('show-config', short_help="Show current CLI configuration")
def show_config():
    """Show current CLI configuration."""
    try:
        config = load_config()
        console.print(create_header("Current Configuration", "Your CLI settings"))
        
        # Create configuration details panel
        config_details = f"""
  API Settings
  URL: {config.get('api_url', 'Not set')}
  Timeout: {config.get('timeout', 'Not set')} seconds

  Configuration File
  Location: {CONFIG_FILE}
  Last Modified: {datetime.fromtimestamp(os.path.getmtime(CONFIG_FILE)).strftime('%Y-%m-%d %H:%M:%S')}
"""
        console.print(create_info_panel("Configuration Details", config_details))
        
        # Create update instructions panel
        update_instructions = f"""
  To update your configuration, you can:

  1. Use the config command:
     dzdk config --url "https://services.dzaleka.com/api" --timeout 30

  2. Use interactive mode:
     dzdk config --interactive

  3. Edit the config file directly:
     {CONFIG_FILE}
"""
        console.print(create_info_panel("How to Update", update_instructions))
    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise click.Abort()

@cli.command('show_config', short_help="Show current CLI configuration")
def show_config_alias():
    """Alias for show-config command."""
    show_config()

@cli.command()
def health():
    """Check API health status."""
    try:
        console.print(create_header("API Health Check", "Monitoring all endpoints"))
        
        # Create a table for endpoint status
        table = Table(
            box=ROUNDED,
            show_header=True,
            header_style="bold cyan",
            border_style="cyan",
            padding=(0, 1),
            expand=True
        )
        
        table.add_column("Endpoint", style="cyan")
        table.add_column("Status", style="bold", justify="center")
        table.add_column("Response Time", style="green", justify="right")
        table.add_column("Details", style="yellow")
        
        all_healthy = True
        
        # Check each endpoint
        for endpoint, path in API_ENDPOINTS.items():
            try:
                start_time = datetime.now()
                response = requests.get(f"{BASE_URL}{path}", timeout=TIMEOUT)
                end_time = datetime.now()
                response_time = (end_time - start_time).total_seconds()
                
                # Check if response is successful
                if 200 <= response.status_code < 300:
                    status = "[bold green]✓[/bold green]"
                    details = "OK"
                else:
                    status = "[bold red]✗[/bold red]"
                    details = f"HTTP {response.status_code}"
                    all_healthy = False
                
                table.add_row(
                    endpoint,
                    status,
                    f"{response_time:.2f}s",
                    details
                )
                
            except requests.exceptions.ConnectionError as e:
                status = "[bold red]✗[/bold red]"
                details = "Connection refused - API server may not be running"
                all_healthy = False
                table.add_row(
                    endpoint,
                    status,
                    "N/A",
                    details
                )
            except requests.exceptions.RequestException as e:
                status = "[bold red]✗[/bold red]"
                details = str(e)
                all_healthy = False
                table.add_row(
                    endpoint,
                    status,
                    "N/A",
                    details
                )
        
        # Display the results
        console.print(table)
        
        # Show overall status and configuration
        if all_healthy:
            console.print("[green]✓ All endpoints are healthy[/green]")
        else:
            console.print("[red]✗ Some endpoints are not responding[/red]")
            console.print("\n[bold yellow]Current Configuration:[/bold yellow]")
            console.print(f"API URL: {BASE_URL}")
            console.print(f"Timeout: {TIMEOUT} seconds")
            console.print("\n[bold yellow]Troubleshooting Steps:[/bold yellow]")
            console.print("1. Verify the API server is running")
            console.print("2. Check if the API URL is correct")
            console.print("3. Ensure network connectivity")
            console.print("4. Try updating the configuration with: dzdk config --url <correct-url>")
            raise click.Abort()
            
    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise click.Abort()

# SERVICES
@cli.group()
def services():
    """Manage Dzaleka services"""
    pass

@services.command("list")
@click.option('--search', help='Search term to filter services')
@click.option('--category', help='Filter by category')
@click.option('--status', type=click.Choice(['active', 'inactive', 'unknown']), help='Filter by status')
@click.option('--sort-by', type=click.Choice(['title', 'category', 'status']), default='title', help='Sort results by field')
@click.option('--sort-order', type=click.Choice(['asc', 'desc']), default='asc', help='Sort order')
@click.option('--page', type=int, default=1, help='Page number to view')
def list_services(search: Optional[str], category: Optional[str], status: Optional[str], sort_by: str, sort_order: str, page: int):
    """List available services (12 per page)"""
    with console.status("[bold green]Fetching services..."):
        try:
            response = requests.get(f"{BASE_URL}/services", timeout=TIMEOUT)
            data = format_response(response)
            
            if data.get('status') == 'error':
                sys.exit(1)
            
            services = data.get('data', {}).get('services', [])
            if not services:
                console.print(create_info_panel("Notice", "[warning]No services found[/warning]"))
                return
            
            # Apply filters
            if search:
                search = search.lower()
                services = [
                    s for s in services
                    if search in s.get('title', '').lower() or
                    search in s.get('description', '').lower() or
                    search in s.get('category', '').lower()
                ]
            
            if category:
                category = category.lower()
                services = [s for s in services if category in s.get('category', '').lower()]
            
            if status:
                status = status.lower()
                services = [s for s in services if status == s.get('status', '').lower()]
            
            # Sort services
            reverse = sort_order == 'desc'
            services.sort(key=lambda x: x.get(sort_by, '').lower(), reverse=reverse)
            
            if not services:
                console.print(create_info_panel("Notice", "[warning]No services match the specified filters[/warning]"))
                return
            
            # Pagination
            total_services = len(services)
            services_per_page = 12
            total_pages = (total_services + services_per_page - 1) // services_per_page
            
            # Validate page number
            if page < 1:
                page = 1
            elif page > total_pages:
                page = total_pages
            
            # Calculate start and end indices for current page
            start_idx = (page - 1) * services_per_page
            end_idx = min(start_idx + services_per_page, total_services)
            
            # Get services for current page
            current_page_services = services[start_idx:end_idx]
            
            console.print(create_header("Available Services", f"Page {page} of {total_pages}"))
            
            table = Table(
                box=ROUNDED,
                show_header=True,
                header_style="bold cyan",
                border_style="cyan",
                padding=(0, 1),
                expand=True,
                width=150,
                show_lines=True,
                row_styles=["", "dim"]
            )
            
            table.add_column("Title", style="cyan", width=30, overflow="crop")
            table.add_column("Category", style="green", width=25, overflow="crop")
            table.add_column("Contact", style="magenta", width=40, overflow="crop")
            table.add_column("Status", style="bold", width=10, justify="center", overflow="crop")
            table.add_column("Website", style="cyan", width=35, overflow="crop")
            
            for service in current_page_services:
                if not isinstance(service, dict):
                    continue
                
                contact = service.get('contact', {})
                contact_lines = []
                if contact.get('email'):
                    email = contact['email'].strip()
                    if email.startswith('📧'):
                        email = email[1:].strip()
                    # Make email clickable with mailto: link
                    contact_lines.append(f"📧 [link=mailto:{email}]{email}[/link]")
                if contact.get('phone'):
                    phone = contact['phone'].strip()
                    if phone.startswith('+'):
                        phone = phone.replace('+', '📞 +')
                    else:
                        phone = f"📞 {phone}"
                    # Make phone clickable with tel: link
                    # Remove any non-digit characters for the tel: link
                    tel_number = ''.join(filter(str.isdigit, phone))
                    contact_lines.append(f"[link=tel:{tel_number}]{phone}[/link]")
                contact_str = "\n".join(contact_lines) if contact_lines else "N/A"
                
                status = service.get('status', 'N/A').strip().lower()
                if status == 'active':
                    status = "[bold green]●[/bold green]"
                elif status == 'inactive':
                    status = "[bold red]●[/bold red]"
                else:
                    status = "[bold yellow]●[/bold yellow]"
                
                website = service.get('socialMedia', {}).get('website', '')
                if website and website != "N/A":
                    import re
                    match = re.search(r"https?://([^/]+)", website)
                    display_url = match.group(1) if match else website
                    display_url = display_url.replace('www.', '')
                    # Make the website clickable
                    website = f"[link={website}]{display_url}[/link]"
                else:
                    website = "N/A"
                
                table.add_row(
                    service.get('title', 'N/A').strip(),
                    service.get('category', 'N/A').strip(),
                    contact_str,
                    status,
                    website
                )
            
            console.print(table)
            
            # Show navigation instructions
            navigation_panel = Panel(
                f"""
[bold]Navigation Commands:[/bold]
• To view next page: [cyan]dzdk services list --page {page + 1}[/cyan]
• To view previous page: [cyan]dzdk services list --page {page - 1}[/cyan]
• To view specific page: [cyan]dzdk services list --page <number>[/cyan]

[dim]Showing services {start_idx + 1}-{end_idx} of {total_services}[/dim]
                """,
                title="Navigation Help",
                border_style="cyan",
                box=ROUNDED
            )
            console.print(navigation_panel)
            
        except requests.exceptions.RequestException as e:
            console.print(create_info_panel("Error", f"[danger]Error fetching services: {str(e)}[/danger]"))
            sys.exit(1)

@services.command("get")
@click.option('--id', required=True, help="Service ID or slug")
def get_service(id: str):
    """Get details for a specific service"""
    with console.status(f"[bold green]Fetching service {id}..."):
        try:
            response = requests.get(f"{BASE_URL}/services", timeout=TIMEOUT)
            data = format_response(response)
            
            if data.get('status') != 'success':
                console.print("[red]Failed to fetch services[/red]")
                sys.exit(1)
                
            services = data.get('data', {}).get('services', [])
            service = next((s for s in services if s.get('id') == id or s.get('slug') == id), None)
            
            if not service:
                console.print(f"[red]Service not found: {id}[/red]")
                sys.exit(1)
            
            # Format contact information
            contact = service.get('contact', {})
            contact_info = []
            if contact.get('email'):
                email = contact['email'].strip()
                if email.startswith('📧'):
                    email = email[1:].strip()
                contact_info.append(f"📧 [link=mailto:{email}]{email}[/link]")
            if contact.get('phone'):
                phone = contact['phone'].strip()
                if phone.startswith('+'):
                    phone = phone.replace('+', '📞 +')
                else:
                    phone = f"📞 {phone}"
                tel_number = ''.join(filter(str.isdigit, phone))
                contact_info.append(f"[link=tel:{tel_number}]{phone}[/link]")
            
            # Format social media
            social_media = service.get('socialMedia', {})
            social_info = []
            
            # Website
            if social_media.get('website'):
                website = social_media['website']
                if website and website != "N/A":
                    import re
                    match = re.search(r"https?://([^/]+)", website)
                    display_url = match.group(1) if match else website
                    display_url = display_url.replace('www.', '')
                    social_info.append(f"🌐 [link={website}]{display_url}[/link]")
            
            # Facebook
            if social_media.get('facebook'):
                fb_url = social_media['facebook']
                if fb_url and fb_url != "N/A":
                    social_info.append(f"📘 [link={fb_url}]Facebook[/link]")
            
            # Twitter/X
            if social_media.get('twitter'):
                twitter_url = social_media['twitter']
                if twitter_url and twitter_url != "N/A":
                    social_info.append(f"🐦 [link={twitter_url}]Twitter[/link]")
            
            # Instagram
            if social_media.get('instagram'):
                insta_url = social_media['instagram']
                if insta_url and insta_url != "N/A":
                    social_info.append(f"📸 [link={insta_url}]Instagram[/link]")
            
            # LinkedIn
            if social_media.get('linkedin'):
                linkedin_url = social_media['linkedin']
                if linkedin_url and linkedin_url != "N/A":
                    social_info.append(f"💼 [link={linkedin_url}]LinkedIn[/link]")
            
            # WhatsApp
            if social_media.get('whatsapp'):
                whatsapp = social_media['whatsapp']
                if whatsapp and whatsapp != "N/A":
                    # Clean the number for the link
                    whatsapp_number = ''.join(filter(str.isdigit, whatsapp))
                    social_info.append(f"💬 [link=https://wa.me/{whatsapp_number}]WhatsApp[/link]")
            
            # YouTube
            if social_media.get('youtube'):
                youtube_url = social_media['youtube']
                if youtube_url and youtube_url != "N/A":
                    social_info.append(f"🎥 [link={youtube_url}]YouTube[/link]")
            
            # TikTok
            if social_media.get('tiktok'):
                tiktok_url = social_media['tiktok']
                if tiktok_url and tiktok_url != "N/A":
                    social_info.append(f"🎵 [link={tiktok_url}]TikTok[/link]")
            
            # Create service details panel
            console.print(Panel(
                f"""
[bold]Service Details[/bold]
Title: {service.get('title', 'N/A')}
Description: {service.get('description', 'N/A')}
Category: {service.get('category', 'N/A')}
Status: {service.get('status', 'N/A')}
{'[bold green]✓ Featured Service[/bold green]' if service.get('featured') else ''}
{'[bold blue]✓ Verified[/bold blue]' if service.get('verified') else ''}

[bold]Contact Information[/bold]
{chr(10).join(contact_info) if contact_info else 'N/A'}
Hours: {contact.get('hours', 'N/A')}

[bold]Social Media & Online Presence[/bold]
{chr(10).join(social_info) if social_info else 'N/A'}

[bold]Location[/bold]
Address: {service.get('location', {}).get('address', 'N/A')}
City: {service.get('location', {}).get('city', 'N/A')}
Coordinates: {f"Lat: {service.get('location', {}).get('coordinates', {}).get('lat', 'N/A')}, Lng: {service.get('location', {}).get('coordinates', {}).get('lng', 'N/A')}"}

[bold]Additional Information[/bold]
Last Updated: {datetime.fromisoformat(service.get('lastUpdated', '').replace('Z', '+00:00')).strftime('%Y-%m-%d %H:%M') if service.get('lastUpdated') else 'N/A'}
Languages: {', '.join(service.get('languages', ['N/A']))}
Tags: {', '.join(service.get('tags', ['N/A']))}
                """,
                title=f"Service: {service.get('title', 'N/A')}",
                border_style="green",
                box=ROUNDED
            ))
            
        except requests.exceptions.RequestException as e:
            console.print(create_info_panel("Error", f"[danger]Error fetching service: {str(e)}[/danger]"))
            sys.exit(1)

# EVENTS
@cli.group()
def events():
    """Manage Dzaleka events"""
    pass

@events.command("list")
@click.option('--search', help='Search term to filter events')
@click.option('--category', help='Filter by category')
@click.option('--status', type=click.Choice(['active', 'inactive', 'unknown']), help='Filter by status')
@click.option('--sort-by', type=click.Choice(['title', 'category', 'status']), default='title', help='Sort results by field')
@click.option('--sort-order', type=click.Choice(['asc', 'desc']), default='asc', help='Sort order')
@click.option('--page', type=int, default=1, help='Page number to view')
def list_events(search: Optional[str], category: Optional[str], status: Optional[str], sort_by: str, sort_order: str, page: int):
    """List available events (12 per page)"""
    with console.status("[bold green]Fetching events..."):
        response = requests.get(f"{BASE_URL}/events", timeout=TIMEOUT)
        data = format_response(response)
        
        if data.get('status') != 'success':
            console.print("[red]Failed to fetch events[/red]")
            sys.exit(1)
            
        events = data.get('data', {}).get('events', [])
        
        # Apply filters
        if search:
            search = search.lower()
            events = [
                e for e in events
                if search in e.get('title', '').lower() or
                search in e.get('description', '').lower() or
                search in e.get('category', '').lower()
            ]
        
        if category:
            category = category.lower()
            events = [e for e in events if category in e.get('category', '').lower()]
        
        if status:
            status = status.lower()
            events = [e for e in events if status == e.get('status', '').lower()]
        
        # Sort events
        reverse = sort_order == 'desc'
        events.sort(key=lambda x: x.get(sort_by, '').lower(), reverse=reverse)
        
        # Pagination
        total_events = len(events)
        events_per_page = 12
        total_pages = (total_events + events_per_page - 1) // events_per_page
        
        # Validate page number
        if page < 1:
            page = 1
        elif page > total_pages:
            page = total_pages
        
        # Calculate start and end indices for current page
        start_idx = (page - 1) * events_per_page
        end_idx = min(start_idx + events_per_page, total_events)
        
        # Get events for current page
        current_page_events = events[start_idx:end_idx]
        
        table = Table(
            title=f"Available Events (Page {page} of {total_pages})",
            show_lines=True,
            box=ROUNDED
        )
        table.add_column("Title", style="cyan")
        table.add_column("Date", style="green")
        table.add_column("Location", style="yellow")
        table.add_column("Status", style="magenta")
        table.add_column("Category", style="blue")
        
        for event in current_page_events:
            date = datetime.fromisoformat(event['date'].replace('Z', '+00:00'))
            formatted_date = date.strftime('%Y-%m-%d %H:%M')
            
            table.add_row(
                event.get('title', 'N/A'),
                formatted_date,
                event.get('location', 'N/A'),
                event.get('status', 'N/A'),
                event.get('category', 'N/A')
            )
        
        console.print(table)
        
        # Show navigation instructions
        navigation_panel = Panel(
            f"""
[bold]Navigation Commands:[/bold]
• To view next page: [cyan]dzdk events list --page {page + 1}[/cyan]
• To view previous page: [cyan]dzdk events list --page {page - 1}[/cyan]
• To view specific page: [cyan]dzdk events list --page <number>[/cyan]

[dim]Showing events {start_idx + 1}-{end_idx} of {total_events}[/dim]
            """,
            title="Navigation Help",
            border_style="cyan",
            box=ROUNDED
        )
        console.print(navigation_panel)

@events.command("get")
@click.option('--id', required=True, help="Event ID or slug")
def get_event(id):
    """Get details for a specific event"""
    with console.status(f"[bold green]Fetching event {id}..."):
        response = requests.get(f"{BASE_URL}/events", timeout=TIMEOUT)
        data = format_response(response)
        
        if data.get('status') != 'success':
            console.print("[red]Failed to fetch events[/red]")
            sys.exit(1)
            
        events = data.get('data', {}).get('events', [])
        event = next((e for e in events if e.get('id') == id or e.get('slug') == id), None)
        
        if not event:
            console.print(f"[red]Event not found: {id}[/red]")
            sys.exit(1)
        
        # Format dates
        start_date = datetime.fromisoformat(event['date'].replace('Z', '+00:00'))
        formatted_start = start_date.strftime('%Y-%m-%d %H:%M')
        
        end_date = None
        if event.get('endDate'):
            end_date = datetime.fromisoformat(event['endDate'].replace('Z', '+00:00'))
            formatted_end = end_date.strftime('%Y-%m-%d %H:%M')
        
        # Create contact info
        contact = event.get('contact', {})
        contact_info = f"Email: {contact.get('email', 'N/A')}\n"
        contact_info += f"Phone: {contact.get('phone', 'N/A')}\n"
        if contact.get('whatsapp'):
            contact_info += f"WhatsApp: {contact['whatsapp']}\n"
        
        # Create registration info
        registration = event.get('registration', {})
        reg_info = f"Registration Required: {'Yes' if registration.get('required') else 'No'}\n"
        if registration.get('url'):
            reg_info += f"Registration URL: {registration['url']}\n"
        if registration.get('deadline'):
            deadline = datetime.fromisoformat(registration['deadline'].replace('Z', '+00:00'))
            reg_info += f"Registration Deadline: {deadline.strftime('%Y-%m-%d %H:%M')}\n"
        
        # Create tags info
        tags = ', '.join(event.get('tags', []))
        
        console.print(Panel(
            f"[bold]Event Details[/bold]\n"
            f"Title: {event.get('title', 'N/A')}\n"
            f"Description: {event.get('description', 'N/A')}\n"
            f"Date: {formatted_start}\n"
            f"{f'End Date: {formatted_end}\n' if end_date else ''}"
            f"Location: {event.get('location', 'N/A')}\n"
            f"Category: {event.get('category', 'N/A')}\n"
            f"Organizer: {event.get('organizer', 'N/A')}\n"
            f"Status: {event.get('status', 'N/A')}\n"
            f"Tags: {tags}\n\n"
            f"[bold]Contact Information[/bold]\n{contact_info}\n"
            f"[bold]Registration[/bold]\n{reg_info}",
            title=f"Event: {event.get('title', 'N/A')}",
            border_style="green"
        ))

# PHOTOS
@cli.group()
def photos():
    """Manage photo uploads and listings"""
    pass

@photos.command("list")
@click.option('--search', help='Search term to filter photos')
@click.option('--category', help='Filter by category')
@click.option('--status', type=click.Choice(['active', 'inactive', 'unknown']), help='Filter by status')
@click.option('--sort-by', type=click.Choice(['title', 'category', 'status']), default='title', help='Sort results by field')
@click.option('--sort-order', type=click.Choice(['asc', 'desc']), default='asc', help='Sort order')
@click.option('--page', type=int, default=1, help='Page number to view')
def list_photos(search: Optional[str], category: Optional[str], status: Optional[str], sort_by: str, sort_order: str, page: int):
    """List available photos (12 per page)"""
    with console.status("[bold green]Fetching photos..."):
        response = requests.get(f"{BASE_URL}/photos", timeout=TIMEOUT)
        data = format_response(response)
        
        if data.get('status') != 'success':
            console.print("[red]Failed to fetch photos[/red]")
            sys.exit(1)
            
        photos = data.get('data', {}).get('photos', [])
        
        # Apply filters
        if search:
            search = search.lower()
            photos = [
                p for p in photos
                if search in p.get('title', '').lower() or
                search in p.get('description', '').lower() or
                search in p.get('category', '').lower()
            ]
        
        if category:
            category = category.lower()
            photos = [p for p in photos if category in p.get('category', '').lower()]
        
        if status:
            status = status.lower()
            photos = [p for p in photos if status == p.get('status', '').lower()]
        
        # Sort photos
        reverse = sort_order == 'desc'
        photos.sort(key=lambda x: x.get(sort_by, '').lower(), reverse=reverse)
        
        # Pagination
        total_photos = len(photos)
        photos_per_page = 12
        total_pages = (total_photos + photos_per_page - 1) // photos_per_page
        
        # Validate page number
        if page < 1:
            page = 1
        elif page > total_pages:
            page = total_pages
        
        # Calculate start and end indices for current page
        start_idx = (page - 1) * photos_per_page
        end_idx = min(start_idx + photos_per_page, total_photos)
        
        # Get photos for current page
        current_page_photos = photos[start_idx:end_idx]
        
        table = Table(
            title=f"Available Photos (Page {page} of {total_pages})",
            show_lines=True,
            box=ROUNDED
        )
        table.add_column("Title", style="cyan")
        table.add_column("Date", style="green")
        table.add_column("Photographer", style="yellow")
        table.add_column("Location", style="magenta")
        table.add_column("Tags", style="blue")
        
        for photo in current_page_photos:
            date = datetime.fromisoformat(photo['date'].replace('Z', '+00:00'))
            formatted_date = date.strftime('%Y-%m-%d')
            
            photographer = photo.get('photographer', {})
            photographer_name = photographer.get('name', 'N/A')
            
            tags = ', '.join(photo.get('tags', []))
            
            table.add_row(
                photo.get('title', 'N/A'),
                formatted_date,
                photographer_name,
                photo.get('location', 'N/A'),
                tags
            )
        
        console.print(table)
        
        # Show navigation instructions
        navigation_panel = Panel(
            f"""
[bold]Navigation Commands:[/bold]
• To view next page: [cyan]dzdk photos list --page {page + 1}[/cyan]
• To view previous page: [cyan]dzdk photos list --page {page - 1}[/cyan]
• To view specific page: [cyan]dzdk photos list --page <number>[/cyan]

[dim]Showing photos {start_idx + 1}-{end_idx} of {total_photos}[/dim]
            """,
            title="Navigation Help",
            border_style="cyan",
            box=ROUNDED
        )
        console.print(navigation_panel)

@photos.command("upload")
@click.option('--file', required=True, type=click.Path(exists=True), help="Path to image")
@click.option('--title', required=True, help="Title for the photo")
@click.option('--description', help="Description of the photo")
def upload_photo(file, title, description: Optional[str] = None):
    """Upload a photo to the Dzaleka archive"""
    console.print(create_header("Photo Upload", "Uploading photo to the archive"))
    
    if not os.path.exists(file):
        console.print(create_info_panel("Error", f"[danger]File not found: {file}[/danger]"))
        sys.exit(1)

    file_size = os.path.getsize(file)
    if file_size > 10 * 1024 * 1024:  # 10MB limit
        console.print(create_info_panel("Error", "[danger]File size exceeds 10MB limit[/danger]"))
        sys.exit(1)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeRemainingColumn(),
        console=console
    ) as progress:
        task = progress.add_task("[cyan]Uploading photo...", total=100)
        
        try:
            with open(file, 'rb') as f:
                files = {'file': f}
                data = {'title': title}
                if description:
                    data['description'] = description
                
                response = requests.post(
                    f"{BASE_URL}/photos",
                    files=files,
                    data=data,
                    timeout=TIMEOUT
                )
                progress.update(task, completed=100)
                
                data = format_response(response)
                console.print(create_info_panel(
                    "Upload Successful",
                    f"""
[success]Photo uploaded successfully![/success]

[highlight]Photo Details:[/highlight]
ID: {data.get('id', 'N/A')}
Title: {data.get('title', 'N/A')}
URL: {data.get('url', 'N/A')}
                    """
                ))
        except Exception as e:
            console.print(create_info_panel("Error", f"[danger]Upload failed: {str(e)}[/danger]"))
            sys.exit(1)

@photos.group()
def album():
    """Manage photo albums"""
    pass

@album.command("create")
@click.option('--name', required=True, help="Album name")
@click.option('--description', help="Album description")
@click.option('--tags', help="Comma-separated list of tags")
def create_album(name: str, description: Optional[str] = None, tags: Optional[str] = None):
    """Create a new photo album"""
    console.print(create_header("Create Album", "Creating a new photo album"))
    
    try:
        data = {
            'name': name,
            'description': description,
            'tags': [tag.strip() for tag in tags.split(',')] if tags else []
        }
        
        response = requests.post(
            f"{BASE_URL}/photos/albums",
            json=data,
            timeout=TIMEOUT
        )
        
        data = format_response(response)
        console.print(create_info_panel(
            "Album Created",
            f"""
[success]Album created successfully![/success]

[highlight]Album Details:[/highlight]
ID: {data.get('id', 'N/A')}
Name: {data.get('name', 'N/A')}
Description: {data.get('description', 'N/A')}
Tags: {', '.join(data.get('tags', []))}
            """
        ))
    except Exception as e:
        console.print(create_info_panel("Error", f"[danger]Failed to create album: {str(e)}[/danger]"))
        sys.exit(1)

@album.command("add")
@click.option('--album-id', required=True, help="Album ID")
@click.option('--photo-ids', required=True, help="Comma-separated list of photo IDs")
def add_to_album(album_id: str, photo_ids: str):
    """Add photos to an album"""
    console.print(create_header("Add to Album", f"Adding photos to album {album_id}"))
    
    photo_list = [pid.strip() for pid in photo_ids.split(',')]
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeRemainingColumn(),
        console=console
    ) as progress:
        task = progress.add_task("[cyan]Adding photos...", total=len(photo_list))
        
        for photo_id in photo_list:
            try:
                response = requests.post(
                    f"{BASE_URL}/photos/albums/{album_id}/photos",
                    json={'photoId': photo_id},
                    timeout=TIMEOUT
                )
                response.raise_for_status()
                progress.update(task, advance=1)
            except Exception as e:
                console.print(f"[yellow]Warning: Failed to add photo {photo_id}: {str(e)}[/yellow]")
    
    console.print(create_info_panel(
        "Photos Added",
        f"Successfully added {len(photo_list)} photos to album {album_id}"
    ))

@album.command("list")
def list_albums():
    """List all photo albums"""
    with console.status("[bold green]Fetching albums..."):
        response = requests.get(f"{BASE_URL}/photos/albums", timeout=TIMEOUT)
        data = format_response(response)
        
        if data.get('status') != 'success':
            console.print("[red]Failed to fetch albums[/red]")
            sys.exit(1)
        
        albums = data.get('data', {}).get('albums', [])
        
        table = create_table("Photo Albums", [
            {"name": "Name", "style": "cyan"},
            {"name": "Description", "style": "green"},
            {"name": "Photos", "style": "yellow"},
            {"name": "Tags", "style": "magenta"}
        ])
        
        for album in albums:
            table.add_row(
                album.get('name', 'N/A'),
                album.get('description', 'N/A'),
                str(album.get('photoCount', 0)),
                ', '.join(album.get('tags', []))
            )
        
        console.print(table)

@photos.command("edit")
@click.option('--id', required=True, help="Photo ID")
@click.option('--title', help="New title")
@click.option('--description', help="New description")
@click.option('--tags', help="Comma-separated list of tags")
@click.option('--location', help="Photo location")
@click.option('--date', help="Photo date (YYYY-MM-DD)")
def edit_photo(id: str, title: Optional[str] = None, description: Optional[str] = None,
               tags: Optional[str] = None, location: Optional[str] = None, date: Optional[str] = None):
    """Edit photo metadata"""
    console.print(create_header("Edit Photo", f"Editing photo {id}"))
    
    try:
        # Get current photo data
        response = requests.get(f"{BASE_URL}/photos/{id}", timeout=TIMEOUT)
        current_data = format_response(response)
        
        if current_data.get('status') != 'success':
            console.print("[red]Failed to fetch photo data[/red]")
            sys.exit(1)
        
        # Prepare update data
        update_data = {}
        if title:
            update_data['title'] = title
        if description:
            update_data['description'] = description
        if tags:
            update_data['tags'] = [tag.strip() for tag in tags.split(',')]
        if location:
            update_data['location'] = location
        if date:
            update_data['date'] = date
        
        # Update photo
        response = requests.patch(
            f"{BASE_URL}/photos/{id}",
            json=update_data,
            timeout=TIMEOUT
        )
        
        data = format_response(response)
        console.print(create_info_panel(
            "Photo Updated",
            f"""
[success]Photo updated successfully![/success]

[highlight]Updated Details:[/highlight]
Title: {data.get('title', 'N/A')}
Description: {data.get('description', 'N/A')}
Location: {data.get('location', 'N/A')}
Date: {data.get('date', 'N/A')}
Tags: {', '.join(data.get('tags', []))}
            """
        ))
    except Exception as e:
        console.print(create_info_panel("Error", f"[danger]Failed to update photo: {str(e)}[/danger]"))
        sys.exit(1)

@photos.command("metadata")
@click.option('--id', required=True, help="Photo ID or slug")
def show_metadata(id: str):
    """Show detailed photo metadata"""
    with console.status(f"[bold green]Fetching metadata for photo {id}..."):
        try:
            response = requests.get(f"{BASE_URL}/photos/{id}", timeout=TIMEOUT)
            data = format_response(response)
            
            if data.get('status') == 'error':
                sys.exit(1)
            
            photo_data = data.get('data', {}).get('photo', {})
            if not photo_data:
                console.print(create_info_panel("Error", "[danger]No photo data found[/danger]"))
                sys.exit(1)
            
            # Create metadata panels
            basic_info = Panel(
                f"""
[bold]Basic Information[/bold]
Title: {photo_data.get('title', 'N/A')}
Description: {photo_data.get('description', 'N/A')}
Date Taken: {photo_data.get('date', 'N/A')}
Location: {photo_data.get('location', 'N/A')}
Photographer: {photo_data.get('photographer', {}).get('name', 'N/A')}
                """,
                title="Basic Info",
                border_style="cyan"
            )
            
            technical_info = Panel(
                f"""
[bold]Technical Information[/bold]
Camera: {photo_data.get('camera', 'N/A')}
Lens: {photo_data.get('lens', 'N/A')}
Exposure: {photo_data.get('exposure', 'N/A')}
Aperture: {photo_data.get('aperture', 'N/A')}
ISO: {photo_data.get('iso', 'N/A')}
Focal Length: {photo_data.get('focalLength', 'N/A')}
                """,
                title="Technical Info",
                border_style="green"
            )
            
            file_info = Panel(
                f"""
[bold]File Information[/bold]
Format: {photo_data.get('format', 'N/A')}
Size: {photo_data.get('size', 'N/A')}
Dimensions: {photo_data.get('dimensions', 'N/A')}
Resolution: {photo_data.get('resolution', 'N/A')}
URL: {photo_data.get('url', 'N/A')}
                """,
                title="File Info",
                border_style="yellow"
            )
            
            console.print(basic_info)
            console.print(technical_info)
            console.print(file_info)
            
        except requests.exceptions.RequestException as e:
            console.print(create_info_panel("Error", f"[danger]Error fetching photo data: {str(e)}[/danger]"))
            sys.exit(1)

# POPULATION
@cli.group()
def population():
    """Access population data"""
    pass

@population.command("stats")
def get_population():
    """Get current population statistics"""
    with console.status("[bold green]Fetching population statistics...[/bold green]", spinner="dots"):
        response = requests.get(f"{BASE_URL}/population", timeout=TIMEOUT)
        data = format_response(response)
        
        # Create main statistics panel
        main_stats = Panel(
            f"[bold]Total Population:[/bold] {data.get('total', 'N/A'):,}\n"
            f"[bold]New Arrivals:[/bold] {data.get('newArrivals', 'N/A'):,}",
            title="Population Overview",
            border_style="green",
            box=ROUNDED
        )
        console.print(main_stats)
        
        # Create demographics visualization
        demographics = data.get('demographics', {})
        demo_table = create_table("Demographics Distribution", [
            {"name": "Category", "style": "cyan"},
            {"name": "Percentage", "style": "green"},
            {"name": "Visual", "style": "yellow"}
        ])
        
        for category, percentage in demographics.items():
            # Create a visual bar representation
            bar_length = int(percentage / 2)  # Scale down for terminal display
            bar = "█" * bar_length
            demo_table.add_row(
                category.capitalize(),
                f"{percentage}%",
                f"[yellow]{bar}[/yellow]"
            )
        
        console.print(demo_table)
        
        # Create nationalities visualization
        nationalities = data.get('nationalities', {})
        nat_table = create_table("Nationalities Distribution", [
            {"name": "Country", "style": "cyan"},
            {"name": "Percentage", "style": "green"},
            {"name": "Visual", "style": "magenta"}
        ])
        
        for country, percentage in nationalities.items():
            # Create a visual bar representation
            bar_length = int(percentage / 2)  # Scale down for terminal display
            bar = "█" * bar_length
            nat_table.add_row(
                country,
                f"{percentage}%",
                f"[magenta]{bar}[/magenta]"
            )
        
        console.print(nat_table)
        
        # Create population trends visualization
        trends = data.get('trends', {})
        trend_table = create_table("Population Trends Over Time", [
            {"name": "Year", "style": "cyan"},
            {"name": "Population", "style": "green"},
            {"name": "Trend", "style": "blue"}
        ])
        
        # Calculate the scale factor for visualization
        values = trends.get('values', [])
        if values:
            max_value = max(values)
            scale_factor = 50 / max_value  # Scale to max 50 characters
            
            for year, population in zip(trends.get('labels', []), values):
                # Create a visual trend representation
                bar_length = int(population * scale_factor)
                bar = "█" * bar_length
                trend_table.add_row(
                    year,
                    f"{population:,}",
                    f"[blue]{bar}[/blue]"
                )
        
        console.print(trend_table)
        
        # Add a legend panel
        console.print(Panel(
            "[bold]Visualization Legend[/bold]\n"
            "█ - Represents percentage or population value\n"
            "Each █ represents approximately 2% for demographics and nationalities\n"
            "Population trends are scaled relative to the maximum value",
            title="Legend",
            border_style="cyan",
            box=ROUNDED
        ))

# RESOURCES
@cli.group()
def resources():
    """Manage digital resources"""
    pass

@resources.command("list")
@click.option('--page', type=int, default=1, help='Page number to view')
def list_resources(page: int):
    """List available resources (12 per page)"""
    with console.status("[bold green]Fetching resources..."):
        response = requests.get(f"{BASE_URL}/resources", timeout=TIMEOUT)
        data = format_response(response)
        
        if data.get('status') != 'success':
            console.print("[red]Failed to fetch resources[/red]")
            sys.exit(1)
            
        resources = data.get('data', {}).get('resources', [])
        total_resources = len(resources)
        resources_per_page = 12
        total_pages = (total_resources + resources_per_page - 1) // resources_per_page
        
        # Validate page number
        if page < 1:
            page = 1
        elif page > total_pages:
            page = total_pages
        
        # Calculate start and end indices for current page
        start_idx = (page - 1) * resources_per_page
        end_idx = min(start_idx + resources_per_page, total_resources)
        
        # Get resources for current page
        current_page_resources = resources[start_idx:end_idx]
        
        table = Table(
            title=f"Available Resources (Page {page} of {total_pages})",
            show_lines=True,
            box=ROUNDED
        )
        table.add_column("Title", style="cyan")
        table.add_column("Category", style="green")
        table.add_column("Author", style="yellow")
        table.add_column("Date", style="magenta")
        table.add_column("File Type", style="blue")
        
        for resource in current_page_resources:
            date = datetime.fromisoformat(resource['date'].replace('Z', '+00:00'))
            formatted_date = date.strftime('%Y-%m-%d')
            
            # Create clickable title with resource URL
            title = resource.get('title', 'N/A')
            resource_url = resource.get('resourceUrl', '')
            if resource_url:
                title = f"[link={resource_url}]{title}[/link]"
            
            table.add_row(
                title,
                resource.get('category', 'N/A'),
                resource.get('author', 'N/A'),
                formatted_date,
                resource.get('fileType', 'N/A')
            )
        
        console.print(table)
        
        # Show navigation instructions
        navigation_panel = Panel(
            f"""
[bold]Navigation Commands:[/bold]
• To view next page: [cyan]dzdk resources list --page {page + 1}[/cyan]
• To view previous page: [cyan]dzdk resources list --page {page - 1}[/cyan]
• To view specific page: [cyan]dzdk resources list --page <number>[/cyan]

[dim]Showing resources {start_idx + 1}-{end_idx} of {total_resources}[/dim]
            """,
            title="Navigation Help",
            border_style="cyan",
            box=ROUNDED
        )
        console.print(navigation_panel)

@resources.command("get")
@click.option('--id', required=True, help="Resource ID or slug")
def get_resource(id):
    """Get details for a specific resource"""
    with console.status(f"[bold green]Fetching resource {id}..."):
        response = requests.get(f"{BASE_URL}/resources", timeout=TIMEOUT)
        data = format_response(response)
        
        if data.get('status') != 'success':
            console.print("[red]Failed to fetch resources[/red]")
            sys.exit(1)
            
        resources = data.get('data', {}).get('resources', [])
        resource = next((r for r in resources if r.get('id') == id or r.get('slug') == id), None)
        
        if not resource:
            console.print(f"[red]Resource not found: {id}[/red]")
            sys.exit(1)
        
        date = datetime.fromisoformat(resource['date'].replace('Z', '+00:00'))
        formatted_date = date.strftime('%Y-%m-%d')
        
        last_updated = datetime.fromisoformat(resource['lastUpdated'].replace('Z', '+00:00'))
        formatted_last_updated = last_updated.strftime('%Y-%m-%d')
        
        console.print(Panel(
            f"[bold]Resource Details[/bold]\n"
            f"Title: {resource.get('title', 'N/A')}\n"
            f"Description: {resource.get('description', 'N/A')}\n"
            f"Category: {resource.get('category', 'N/A')}\n"
            f"Author: {resource.get('author', 'N/A')}\n"
            f"Date: {formatted_date}\n"
            f"Last Updated: {formatted_last_updated}\n"
            f"File Type: {resource.get('fileType', 'N/A')}\n"
            f"File Size: {resource.get('fileSize', 'N/A')}\n"
            f"Languages: {', '.join(resource.get('languages', []))}\n\n"
            f"[bold]Download Information[/bold]\n"
            f"Download URL: {resource.get('downloadUrl', 'N/A')}\n"
            f"Resource URL: {resource.get('resourceUrl', 'N/A')}",
            title=f"Resource: {resource.get('title', 'N/A')}",
            border_style="green"
        ))

@resources.command("fetch")
@click.option('--id', required=True, help="Resource ID or slug")
@click.option('--output', required=True, type=str, help="Output file name")
def fetch_resource(id, output):
    """Download a resource file"""
    console.print(create_header("Fetch Resource", f"Downloading resource {id}"))
    
    try:
        # Get resource details
        response = requests.get(f"{BASE_URL}/resources/{id}", timeout=TIMEOUT)
        data = format_response(response)
        
        if data.get('status') != 'success':
            console.print("[red]Failed to fetch resource details[/red]")
            sys.exit(1)
        
        resource = data.get('data', {}).get('resource')
        if not resource:
            console.print("[red]Resource not found[/red]")
            sys.exit(1)
        
        # Get download URL
        download_url = resource.get('downloadUrl')
        if not download_url:
            console.print("[red]No download URL available[/red]")
            sys.exit(1)
        
        # Get file size for progress bar
        head = requests.head(download_url, timeout=TIMEOUT)
        total_size = int(head.headers.get('content-length', 0))
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("[cyan]Downloading...", total=total_size)
            
        with open(output, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    progress.update(task, advance=len(chunk))
            
            console.print(f"[green]Resource successfully saved to {output}[/green]")
    except requests.exceptions.RequestException as e:
        console.print(f"[red]Download failed: {str(e)}[/red]")
        sys.exit(1)

@cli.command()
@click.option('--query', required=True, help='Search query')
@click.option('--type', type=click.Choice(['all', 'services', 'events', 'photos', 'resources']), default='all', help='Type of content to search')
@click.option('--limit', type=int, default=10, help='Maximum number of results to return')
def search(query: str, type: str, limit: int):
    """Search across all resources"""
    console.print(create_header("Search Results", f"Searching for: {query}"))
    
    results = []
    search_types = ['services', 'events', 'photos', 'resources'] if type == 'all' else [type]
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:
        task = progress.add_task("[cyan]Searching...", total=len(search_types))
        
        for search_type in search_types:
            try:
                response = requests.get(f"{BASE_URL}/{search_type}", timeout=TIMEOUT)
                data = format_response(response)
                
                if data.get('status') == 'success':
                    items = data.get('data', {}).get(search_type, [])
                    
                    # Search in relevant fields
                    for item in items:
                        searchable_fields = {
                            'services': ['title', 'description', 'category'],
                            'events': ['title', 'description', 'category', 'location'],
                            'photos': ['title', 'description', 'location', 'tags'],
                            'resources': ['title', 'description', 'category', 'author']
                        }
                        
                        # Check if query matches any searchable field
                        if any(
                            query.lower() in str(item.get(field, '')).lower()
                            for field in searchable_fields.get(search_type, [])
                        ):
                            results.append({
                                'type': search_type,
                                'item': item
                            })
                
            except requests.exceptions.RequestException as e:
                console.print(f"[yellow]Warning: Error searching {search_type}: {str(e)}[/yellow]")
            
            progress.update(task, advance=1)
    
    # Sort results by relevance (simple implementation)
    results.sort(key=lambda x: sum(
        query.lower() in str(x['item'].get(field, '')).lower()
        for field in ['title', 'description']
    ), reverse=True)
    
    # Limit results
    results = results[:limit]
    
    if not results:
        console.print(create_info_panel("No Results", "[warning]No matching items found[/warning]"))
        return
    
    # Display results
    for result in results:
        item = result['item']
        item_type = result['type']
        
        # Create a panel for each result
        title = item.get('title', 'N/A')
        description = item.get('description', 'N/A')
        
        # Format additional details based on type
        details = []
        if item_type == 'services':
            contact = item.get('contact', {})
            details.append(f"Contact: {contact.get('email', 'N/A')}")
            details.append(f"Location: {item.get('location', {}).get('address', 'N/A')}")
        elif item_type == 'events':
            date = datetime.fromisoformat(item['date'].replace('Z', '+00:00'))
            details.append(f"Date: {date.strftime('%Y-%m-%d %H:%M')}")
            details.append(f"Location: {item.get('location', 'N/A')}")
        elif item_type == 'photos':
            photographer = item.get('photographer', {}).get('name', 'N/A')
            details.append(f"Photographer: {photographer}")
            details.append(f"Location: {item.get('location', 'N/A')}")
        elif item_type == 'resources':
            details.append(f"Author: {item.get('author', 'N/A')}")
            details.append(f"Category: {item.get('category', 'N/A')}")
        
        # Create the result panel
        result_text = f"[bold]{title}[/bold]\n"
        result_text += f"{description}\n\n"
        result_text += "\n".join(details)
        
        console.print(Panel(
            result_text,
            title=f"[cyan]{item_type.capitalize()}[/cyan]",
            border_style="green",
            box=ROUNDED
        ))
    
    # Show summary
    console.print(create_info_panel(
        "Search Summary",
        f"Found {len(results)} results across {len(search_types)} categories"
    ))

@cli.group()
def batch():
    """Batch operations for resources and photos"""
    pass

@batch.command("download")
@click.option('--type', type=click.Choice(['resources', 'photos']), required=True, help='Type of content to download')
@click.option('--ids', required=True, help='Comma-separated list of IDs to download')
@click.option('--output-dir', type=click.Path(), default='downloads', help='Output directory for downloads')
def batch_download(type: str, ids: str, output_dir: str):
    """Download multiple resources or photos in batch"""
    console.print(create_header("Batch Download", f"Downloading {type}"))
    
    # Create output directory if it doesn't exist
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Parse IDs
    id_list = [id.strip() for id in ids.split(',')]
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeRemainingColumn(),
        console=console
    ) as progress:
        task = progress.add_task(f"[cyan]Downloading {type}...", total=len(id_list))
        
        for item_id in id_list:
            try:
                # Get item details
                response = requests.get(f"{BASE_URL}/{type}", timeout=TIMEOUT)
                data = format_response(response)
                
                if data.get('status') != 'success':
                    console.print(f"[yellow]Warning: Failed to fetch {type} details[/yellow]")
                    continue
                
                items = data.get('data', {}).get(type, [])
                item = next((i for i in items if i.get('id') == item_id or i.get('slug') == item_id), None)
                
                if not item:
                    console.print(f"[yellow]Warning: {type} not found: {item_id}[/yellow]")
                    continue
                
                # Get download URL
                download_url = item.get('downloadUrl') if type == 'resources' else item.get('url')
                if not download_url:
                    console.print(f"[yellow]Warning: No download URL for {item_id}[/yellow]")
                    continue
                
                # Download file
                response = requests.get(download_url, stream=True, timeout=TIMEOUT)
                response.raise_for_status()
                
                # Determine filename
                filename = item.get('title', item_id)
                if type == 'resources':
                    filename = f"{filename}.{item.get('fileType', 'pdf')}"
                else:
                    filename = f"{filename}.jpg"

                # Save file
                file_path = output_path / filename
                with open(file_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            progress.update(task, advance=len(chunk))
                
                console.print(f"[green]Downloaded: {filename}[/green]")
                
            except Exception as e:
                console.print(f"[red]Error downloading {item_id}: {str(e)}[/red]")
            
            progress.update(task, advance=1)
    
    console.print(create_info_panel(
        "Download Complete",
        f"Files have been downloaded to: {output_path.absolute()}"
    ))

@batch.command("upload")
@click.option('--directory', type=click.Path(exists=True), required=True, help='Directory containing files to upload')
@click.option('--type', type=click.Choice(['photos']), required=True, help='Type of content to upload')
def batch_upload(directory: str, type: str):
    """Upload multiple files in batch"""
    console.print(create_header("Batch Upload", f"Uploading {type}"))
    
    # Get list of files
    dir_path = Path(directory)
    if type == 'photos':
        files = list(dir_path.glob('*.{jpg,jpeg,png}'))
    else:
        files = []
    
    if not files:
        console.print(create_info_panel("No Files", "[warning]No suitable files found in directory[/warning]"))
        return
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeRemainingColumn(),
        console=console
    ) as progress:
        task = progress.add_task(f"[cyan]Uploading {type}...", total=len(files))
        
        for file in files:
            try:
                # Check file size
                if file.stat().st_size > 10 * 1024 * 1024:  # 10MB limit
                    console.print(f"[yellow]Warning: File too large: {file.name}[/yellow]")
                    continue
                
                # Upload file
                with open(file, 'rb') as f:
                    files = {'file': f}
                    data = {'title': file.stem}
                    
                    response = requests.post(
                        f"{BASE_URL}/{type}",
                        files=files,
                        data=data,
                        timeout=TIMEOUT
                    )
                    
                    data = format_response(response)
                    console.print(f"[green]Uploaded: {file.name}[/green]")
                
            except Exception as e:
                console.print(f"[red]Error uploading {file.name}: {str(e)}[/red]")
            
            progress.update(task, advance=1)
    
    console.print(create_info_panel(
        "Upload Complete",
        f"Successfully processed {len(files)} files"
    ))

@cli.group()
def export():
    """Export data to various formats"""
    pass

@export.command("csv")
@click.option('--type', type=click.Choice(['services', 'events', 'photos', 'resources', 'population']), required=True, help='Type of data to export')
@click.option('--output', type=click.Path(), required=True, help='Output file path')
def export_csv(type: str, output: str):
    """Export data to CSV format"""
    console.print(create_header("CSV Export", f"Exporting {type} data"))
    
    try:
        # Fetch data
        response = requests.get(f"{BASE_URL}/{type}", timeout=TIMEOUT)
        data = format_response(response)
        
        if data.get('status') != 'success':
            console.print("[red]Failed to fetch data[/red]")
            sys.exit(1)
        
        items = data.get('data', {}).get(type, [])
        
        if not items:
            console.print(create_info_panel("No Data", "[warning]No data found to export[/warning]"))
            return
        
        # Flatten nested structures
        flattened_items = []
        for item in items:
            flat_item = {}
            for key, value in item.items():
                if isinstance(value, dict):
                    for subkey, subvalue in value.items():
                        flat_item[f"{key}_{subkey}"] = subvalue
                elif isinstance(value, list):
                    flat_item[key] = ', '.join(str(v) for v in value)
                else:
                    flat_item[key] = value
            flattened_items.append(flat_item)
        
        # Write to CSV
        with open(output, 'w', newline='') as f:
            if flattened_items:
                writer = csv.DictWriter(f, fieldnames=flattened_items[0].keys())
                writer.writeheader()
                writer.writerows(flattened_items)
        
        console.print(create_info_panel(
            "Export Complete",
            f"Data has been exported to: {output}"
        ))
        
    except Exception as e:
        console.print(create_info_panel("Export Failed", f"[danger]Error: {str(e)}[/danger]"))
        sys.exit(1)

@export.command("report")
@click.option('--type', type=click.Choice(['services', 'events', 'photos', 'resources', 'population']), required=True, help='Type of data to report')
@click.option('--output', type=click.Path(), required=True, help='Output file path')
def export_report(type: str, output: str):
    """Generate a detailed report in markdown format"""
    console.print(create_header("Report Generation", f"Generating {type} report"))
    
    try:
        # Fetch data
        response = requests.get(f"{BASE_URL}/{type}", timeout=TIMEOUT)
        data = format_response(response)
        
        if data.get('status') != 'success':
            console.print("[red]Failed to fetch data[/red]")
            sys.exit(1)
        
        items = data.get('data', {}).get(type, [])
        
        if not items:
            console.print(create_info_panel("No Data", "[warning]No data found to report[/warning]"))
            return
        
        # Generate report
        report = f"# {type.capitalize()} Report\n\n"
        report += f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        
        # Add summary
        report += "## Summary\n\n"
        report += f"Total items: {len(items)}\n\n"
        
        # Add detailed information
        report += "## Details\n\n"
        
        for item in items:
            report += f"### {item.get('title', 'Untitled')}\n\n"
            
            # Add all fields
            for key, value in item.items():
                if isinstance(value, dict):
                    report += f"#### {key.capitalize()}\n\n"
                    for subkey, subvalue in value.items():
                        report += f"- **{subkey}**: {subvalue}\n"
                elif isinstance(value, list):
                    report += f"- **{key}**: {', '.join(str(v) for v in value)}\n"
                else:
                    report += f"- **{key}**: {value}\n"
            
            report += "\n---\n\n"
        
        # Write report
        with open(output, 'w') as f:
            f.write(report)
        
        console.print(create_info_panel(
            "Report Generated",
            f"Report has been saved to: {output}"
        ))
        
    except Exception as e:
        console.print(create_info_panel("Report Generation Failed", f"[danger]Error: {str(e)}[/danger]"))
        sys.exit(1)

@cli.group()
def stats():
    """View statistics and analytics"""
    pass

@stats.command("services")
@click.option('--output', type=click.Path(), help='Save report to file')
def service_statistics(output: Optional[str]):
    """Show service distribution and statistics"""
    with console.status("[bold green]Analyzing services..."):
        try:
            # Debug: Print current configuration
            console.print(f"[dim]Using API URL: {BASE_URL}[/dim]")
            
            # Ensure proper URL construction
            api_url = BASE_URL.rstrip('/')
            endpoint = f"{api_url}/services"
            console.print(f"[dim]Requesting: {endpoint}[/dim]")
            
            response = requests.get(endpoint, timeout=TIMEOUT)
            data = format_response(response)
            
            if data.get('status') == 'error':
                sys.exit(1)
            
            services = data.get('data', {}).get('services', [])
            if not services:
                console.print(create_info_panel("Notice", "[warning]No services found[/warning]"))
                return
            
            # Calculate statistics
            total_services = len(services)
            categories = {}
            statuses = {}
            
            for service in services:
                # Category distribution
                category = service.get('category', 'Uncategorized')
                categories[category] = categories.get(category, 0) + 1
                
                # Status distribution
                status = service.get('status', 'unknown').lower()
                statuses[status] = statuses.get(status, 0) + 1
            
            # Create statistics panels
            console.print(create_header("Service Statistics", "Distribution and Analysis"))
            
            # Overall statistics
            overall_stats = Panel(
                f"""
[bold]Total Services:[/bold] {total_services}

[bold]Status Distribution:[/bold]
[green]Active:[/green] {statuses.get('active', 0)} ({statuses.get('active', 0)/total_services*100:.1f}%)
[red]Inactive:[/red] {statuses.get('inactive', 0)} ({statuses.get('inactive', 0)/total_services*100:.1f}%)
[yellow]Unknown:[/yellow] {statuses.get('unknown', 0)} ({statuses.get('unknown', 0)/total_services*100:.1f}%)
                """,
                title="Overall Statistics",
                border_style="cyan",
                box=ROUNDED
            )
            console.print(overall_stats)
            
            # Category distribution
            category_table = Table(
                title="Category Distribution",
                box=ROUNDED,
                show_header=True,
                header_style="bold cyan",
                border_style="cyan"
            )
            category_table.add_column("Category", style="cyan")
            category_table.add_column("Count", style="green", justify="right")
            category_table.add_column("Percentage", style="yellow", justify="right")
            category_table.add_column("Visual", style="magenta")
            
            # Sort categories by count
            sorted_categories = sorted(categories.items(), key=lambda x: x[1], reverse=True)
            
            for category, count in sorted_categories:
                percentage = count / total_services * 100
                # Create visual bar
                bar_length = int(percentage / 2)  # Scale down for terminal display
                bar = "█" * bar_length
                category_table.add_row(
                    category,
                    str(count),
                    f"{percentage:.1f}%",
                    f"[magenta]{bar}[/magenta]"
                )
            
            console.print(category_table)
            
            # Generate report if output file specified
            if output:
                report = f"""# Service Statistics Report
Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## Overall Statistics
- Total Services: {total_services}

### Status Distribution
- Active: {statuses.get('active', 0)} ({statuses.get('active', 0)/total_services*100:.1f}%)
- Inactive: {statuses.get('inactive', 0)} ({statuses.get('inactive', 0)/total_services*100:.1f}%)
- Unknown: {statuses.get('unknown', 0)} ({statuses.get('unknown', 0)/total_services*100:.1f}%)

## Category Distribution
"""
                for category, count in sorted_categories:
                    percentage = count / total_services * 100
                    report += f"- {category}: {count} ({percentage:.1f}%)\n"
                
                with open(output, 'w') as f:
                    f.write(report)
                
                console.print(create_info_panel(
                    "Report Generated",
                    f"Statistics report has been saved to: {output}"
                ))
            
        except requests.exceptions.RequestException as e:
            console.print(create_info_panel("Error", f"[danger]Error fetching services: {str(e)}[/danger]"))
            sys.exit(1)

@stats.command("usage")
@click.option('--days', type=int, default=30, help='Number of days to analyze')
@click.option('--output', type=click.Path(), help='Save report to file')
def usage_statistics(days: int, output: Optional[str]):
    """Show usage statistics and trends"""
    try:
        # Create progress bar for analysis
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeRemainingColumn(),
            console=console
        ) as progress:
            task = progress.add_task("[cyan]Analyzing...", total=100)
            # Simulate analysis (replace with actual API calls)
            for i in range(100):
                time.sleep(0.01)  # Simulate work
                progress.update(task, advance=1)

        # All console.print(...) statements are now outside the 'with' block
        console.print(create_header("Usage Statistics", f"Last {days} days"))

        # Mock data (replace with actual API data)
        usage_stats = {
            'total_requests': 1500,
            'average_response_time': 0.8,
            'success_rate': 98.5,
            'popular_endpoints': [
                ('/services', 450),
                ('/events', 300),
                ('/photos', 250),
                ('/resources', 200),
                ('/population', 150)
            ],
            'error_distribution': {
                'timeout': 15,
                'not_found': 8,
                'server_error': 5,
                'validation_error': 2
            }
        }

        # Overall statistics
        overall_stats = Panel(
            f"""
[bold]Overall Statistics[/bold]
Total Requests: {usage_stats['total_requests']:,}
Average Response Time: {usage_stats['average_response_time']:.2f}s
Success Rate: {usage_stats['success_rate']}%

[bold]Error Distribution[/bold]
Timeout: {usage_stats['error_distribution']['timeout']}
Not Found: {usage_stats['error_distribution']['not_found']}
Server Error: {usage_stats['error_distribution']['server_error']}
Validation Error: {usage_stats['error_distribution']['validation_error']}
            """,
            title="Usage Overview",
            border_style="cyan",
            box=ROUNDED
        )
        console.print(overall_stats)

        # Popular endpoints
        endpoint_table = Table(
            title="Popular Endpoints",
            box=ROUNDED,
            show_header=True,
            header_style="bold cyan",
            border_style="cyan"
        )
        endpoint_table.add_column("Endpoint", style="cyan")
        endpoint_table.add_column("Requests", style="green", justify="right")
        endpoint_table.add_column("Percentage", style="yellow", justify="right")
        endpoint_table.add_column("Visual", style="magenta")

        total_requests = usage_stats['total_requests']
        for endpoint, count in usage_stats['popular_endpoints']:
            percentage = count / total_requests * 100
            bar_length = int(percentage / 2)
            bar = "█" * bar_length
            endpoint_table.add_row(
                endpoint,
                str(count),
                f"{percentage:.1f}%",
                f"[magenta]{bar}[/magenta]"
            )

        console.print(endpoint_table)

        # Generate report if output file specified
        if output:
            report = f"""# Usage Statistics Report
Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Analysis Period: Last {days} days

## Overall Statistics
- Total Requests: {usage_stats['total_requests']:,}
- Average Response Time: {usage_stats['average_response_time']:.2f}s
- Success Rate: {usage_stats['success_rate']}%

## Error Distribution
- Timeout: {usage_stats['error_distribution']['timeout']}
- Not Found: {usage_stats['error_distribution']['not_found']}
- Server Error: {usage_stats['error_distribution']['server_error']}
- Validation Error: {usage_stats['error_distribution']['validation_error']}

## Popular Endpoints
"""
            for endpoint, count in usage_stats['popular_endpoints']:
                percentage = count / total_requests * 100
                report += f"- {endpoint}: {count} requests ({percentage:.1f}%)\n"
            with open(output, 'w') as f:
                f.write(report)
            console.print(create_info_panel(
                "Report Generated",
                f"Usage statistics report has been saved to: {output}"
            ))

    except Exception as e:
        console.print(create_info_panel("Error", f"[danger]Error analyzing usage: {str(e)}[/danger]"))
        sys.exit(1)

class DzdkShell(cmd.Cmd):
    """Interactive shell for Dzaleka Digital Heritage CLI"""
    
    intro = """
╭─────────────────────────────────────────────────────────────────────────╮
│                                                                         │
│  [bold cyan]Welcome to Dzaleka Digital Heritage CLI Shell[/bold cyan]                    │
│  [dim]Type 'help' or '?' to list commands[/dim]                                    │
│                                                                         │
╰─────────────────────────────────────────────────────────────────────────╯
"""
    prompt = 'dzdk> '
    
    def __init__(self):
        super().__init__()
        self.history_file = Path.home() / '.dzdk' / 'history'
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        self.history_file.touch(exist_ok=True)
        
        # Initialize command history
        self.session = PromptSession(
            history=FileHistory(str(self.history_file)),
            auto_suggest=AutoSuggestFromHistory()
        )
        
        # Command completions with categories
        self.commands = {
            'Health': ['health'],
            'Services': ['services list', 'services get'],
            'Events': ['events list', 'events get'],
            'Photos': [
                'photos list', 'photos get', 'photos upload', 'photos metadata',
                'photos edit', 'photos album create', 'photos album add',
                'photos album list'
            ],
            'Population': ['population stats', 'population get'],
            'Resources': ['resources list', 'resources get', 'resources fetch'],
            'Search': ['search'],
            'Batch': ['batch download', 'batch upload'],
            'Export': ['export csv', 'export report'],
            'Config': ['config'],
            'Shell': ['help', 'clear', 'exit']
        }
        
        # Flatten commands for completion
        self.all_commands = [cmd for cmds in self.commands.values() for cmd in cmds]
        self.completer = WordCompleter(self.all_commands)
        
        # Register exit handler
        atexit.register(self.save_history)
    
    def save_history(self):
        """Save command history to file"""
        readline.write_history_file(str(self.history_file))
    
    def default(self, line):
        """Handle commands"""
        try:
            # Split the command into parts
            parts = line.split()
            if not parts:
                return
            
            # Execute the command using Click
            with console.capture() as capture:
                try:
                    cli.main(args=parts, standalone_mode=False)
                except SystemExit:
                    pass
            
            # Print the output
            console.print(capture.get())
            
        except Exception as e:
            console.print(Panel(
                f"[red]Error executing command: {str(e)}[/red]",
                border_style="red"
            ))
    
    def do_clear(self, arg):
        """Clear the terminal screen"""
        os.system('cls' if os.name == 'nt' else 'clear')
        console.print(self.intro)
    
    def do_exit(self, arg):
        """Exit the shell"""
        console.print(Panel(
            "[green]Thank you for using Dzaleka Digital Heritage CLI![/green]",
            border_style="green"
        ))
        return True
    
    def do_help(self, arg):
        """Show help information"""
        if arg:
            # Show help for specific command
            try:
                with console.capture() as capture:
                    cli.main(args=[arg, '--help'], standalone_mode=False)
                console.print(capture.get())
            except SystemExit:
                pass
        else:
            # Show general help with categories
            console.print(Panel(
                "[bold cyan]Available Commands[/bold cyan]",
                border_style="cyan"
            ))
            
            for category, commands in self.commands.items():
                console.print(f"\n[bold yellow]{category}[/bold yellow]")
                for cmd in commands:
                    console.print(f"  [dim]• {cmd}[/dim]")
            
            console.print("\n[bold cyan]Shell Commands[/bold cyan]")
            console.print("  [dim]• help [command] - Show help for a specific command[/dim]")
            console.print("  [dim]• clear - Clear the terminal screen[/dim]")
            console.print("  [dim]• exit - Exit the shell[/dim]")
    
    def complete(self, text, state):
        """Provide command completion"""
        if state == 0:
            if text:
                matches = [cmd for cmd in self.all_commands if cmd.startswith(text)]
            else:
                matches = self.all_commands
            return matches[state]
        return None

@cli.command()
def shell():
    """Start interactive shell mode"""
    try:
        DzdkShell().cmdloop()
    except KeyboardInterrupt:
        console.print("\n[green]Goodbye![/green]")
    except Exception as e:
        console.print(f"[red]Error starting shell: {str(e)}[/red]")

if __name__ == "__main__":
    cli()
