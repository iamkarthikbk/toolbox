#!/usr/bin/env python3

import argparse
from dataclasses import dataclass
from typing import List, Optional, Tuple
import yaml
from PIL import Image, ImageDraw
import colorsys
import math
import json
import os

@dataclass
class PMPEntry:
    addr: int  # Address register value (bits 55-2 for RV64, 33-2 for RV32)
    cfg: int   # Configuration register (R,W,X,A,L fields)
    
    @property
    def readable(self) -> bool:
        return bool(self.cfg & 0x01)  # R bit
    
    @property
    def writable(self) -> bool:
        return bool(self.cfg & 0x02)  # W bit
    
    @property
    def executable(self) -> bool:
        return bool(self.cfg & 0x04)  # X bit
    
    @property
    def address_matching(self) -> int:
        return (self.cfg >> 3) & 0x03  # A field
    
    @property
    def locked(self) -> bool:
        return bool(self.cfg & 0x80)  # L bit

    def get_region_bounds(self, prev_addr: Optional[int] = None) -> Tuple[int, int]:
        """Get the start and end addresses of the PMP region"""
        PMP_SHIFT = 2  # As per RISC-V spec
        XLEN = 64  # Assuming RV64
        
        if self.address_matching == 0:  # OFF
            return (0, 0)
        elif self.address_matching == 1:  # TOR
            if prev_addr is None:
                return (0, self.addr << PMP_SHIFT)
            return (prev_addr << PMP_SHIFT, self.addr << PMP_SHIFT)
        elif self.address_matching == 2:  # NA4
            addr = self.addr << PMP_SHIFT
            return (addr, addr + 4)
        else:  # NAPOT
            # First, find the encoded address (pmpaddr)
            encoded_addr = self.addr
            
            # Find the size by looking at trailing ones
            # Count trailing ones in the encoded address
            trailing_ones = 0
            temp_addr = encoded_addr
            while temp_addr & 1:
                trailing_ones += 1
                temp_addr >>= 1
            
            # Calculate the actual size
            log2len = trailing_ones + PMP_SHIFT + 3  # +3 because minimum NAPOT size is 8 bytes
            
            if log2len == PMP_SHIFT:
                base_addr = encoded_addr << PMP_SHIFT
                size = 4
            else:
                if log2len == XLEN:
                    # Special case: matches the entire address space
                    return (0, (1 << XLEN) - 1)
                else:
                    # Calculate the base address by clearing the trailing ones
                    base_addr = (encoded_addr >> trailing_ones) << (trailing_ones + PMP_SHIFT)
                    size = 1 << log2len
            
            return (base_addr, base_addr + size)

    def check_permission(self, access_addr: int, access_size: Optional[int], access_type: str) -> Optional[str]:
        """Check if the given address falls within this PMP entry and return permissions"""
        start, end = self.get_region_bounds(None)  # We handle prev_addr differently now
        
        # If access_size is specified, check if the entire access region falls within the PMP
        if access_size is not None:
            access_end = access_addr + access_size - 1
            if not (start <= access_addr and access_end < end):
                return None
        elif not (start <= access_addr < end):
            return None
        
        # Check permissions based on access type
        if access_type == 'R' and not self.readable:
            return None
        elif access_type == 'W' and not self.writable:
            return None
        elif access_type == 'X' and not self.executable:
            return None
        
        perms = []
        if self.readable:
            perms.append('R')
        if self.writable:
            perms.append('W')
        if self.executable:
            perms.append('X')
        return ','.join(perms) if perms else 'None'

def generate_pastel_colors(n: int) -> List[Tuple[int, int, int]]:
    """Generate n distinct pastel colors"""
    colors = []
    for i in range(n):
        hue = i / n
        # Pastel colors: high value, low saturation
        sat = 0.3 + (i % 3) * 0.1
        val = 0.9
        rgb = colorsys.hsv_to_rgb(hue, sat, val)
        colors.append(tuple(int(x * 255) for x in rgb))
    return colors

def visualize_pmp_entries(entries: List[PMPEntry], access_addr: Optional[int], 
                         access_size: Optional[int], access_type: Optional[str],
                         min_addr: int, max_addr: int, output_file: str) -> None:
    """Create a PNG visualization of PMP entries and memory access."""
    # Image dimensions
    WIDTH = 1200
    HEIGHT = 700  # Increased height for better label visibility
    PADDING = 80  # Increased padding for labels
    INFO_HEIGHT = 150  # Height for PMP region information
    SPACING = 40  # Spacing between plot and info section
    
    # Address range from YAML
    ADDR_RANGE = max_addr - min_addr
    
    # Create image with white background
    img = Image.new('RGB', (WIDTH, HEIGHT), 'white')
    draw = ImageDraw.Draw(img)
    
    # Scale factor for converting addresses to pixels
    scale = (WIDTH - 2*PADDING) / ADDR_RANGE
    
    # Generate colors for each PMP entry
    colors = generate_pastel_colors(len(entries))
    
    # Draw Y-axis label (rotated 90 degrees counter-clockwise)
    y_label = "PMP Configurations"
    # Create a new image for rotated text with larger dimensions
    font_size = 16  # Larger font size
    from PIL import ImageFont
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
    except:
        font = ImageFont.load_default()
    
    txt_img = Image.new('RGBA', (300, 40), (255, 255, 255, 0))
    txt_draw = ImageDraw.Draw(txt_img)
    txt_draw.text((0, 0), y_label, fill='black', font=font)
    # Rotate and paste
    txt_img = txt_img.rotate(90, expand=True)
    img.paste(txt_img, (15, HEIGHT//2 - 150), txt_img)
    
    # Draw X-axis label
    x_label = "Physical Address"
    x_label_width = draw.textlength(x_label, font=font)
    draw.text((WIDTH//2 - x_label_width//2, HEIGHT - PADDING + 45), x_label, fill='black', font=font)
    
    # Draw PMP regions from bottom to top (earlier entries at bottom)
    for i, (entry, color) in enumerate(zip(entries, colors)):
        prev_addr = entries[i-1].addr if i > 0 else None
        start, end = entry.get_region_bounds(prev_addr)
        
        # Convert addresses to x coordinates
        x1 = PADDING + int((start - min_addr) * scale)
        x2 = PADDING + int((end - min_addr) * scale)
        
        # Clamp to visible range
        x1 = max(PADDING, min(WIDTH - PADDING, x1))
        x2 = max(PADDING, min(WIDTH - PADDING, x2))
        
        # Calculate y coordinates based on entry index (higher entries on top)
        y1 = HEIGHT - PADDING - INFO_HEIGHT - SPACING - (i + 1) * 50
        y2 = y1 + 40
        
        # Draw region rectangle
        draw.rectangle([x1, y1, x2, y2], fill=color)
        
        # Add text label
        perms = []
        if entry.readable: perms.append('R')
        if entry.writable: perms.append('W')
        if entry.executable: perms.append('X')
        if entry.locked: perms.append('L')
        label = f"PMP{i} ({','.join(perms)})"
        draw.text((x1 + 5, y1 + 5), label, fill='black')
        
        # Add PMP region information at the bottom
        info_y = HEIGHT - INFO_HEIGHT + (i * 25) + 10  # Added 10 pixels of padding at top of info section
        mode_map = {0: "OFF", 1: "TOR", 2: "NA4", 3: "NAPOT"}
        mode = mode_map[entry.address_matching]
        info_text = f"PMP{i}: {mode}, Start: 0x{start:08x}, End: 0x{end:08x}"
        if start < min_addr or end > max_addr:
            info_text += " [Partially visible]"
        draw.text((PADDING, info_y), info_text, fill='black')
    
    # Draw access address marker if provided
    if access_addr is not None:
        x = PADDING + int((access_addr - min_addr) * scale)
        
        # Draw access region if size is provided
        if access_size is not None:
            x_end = PADDING + int((access_addr + access_size - min_addr) * scale)
            # Draw semi-transparent red rectangle for access region
            access_region = Image.new('RGBA', (x_end - x, HEIGHT - PADDING - INFO_HEIGHT - SPACING), (255, 0, 0, 64))
            img.paste(access_region, (x, PADDING), access_region)
            # Draw borders of access region
            draw.line([x, PADDING, x, HEIGHT-PADDING-INFO_HEIGHT-SPACING], fill='red', width=2)
            draw.line([x_end, PADDING, x_end, HEIGHT-PADDING-INFO_HEIGHT-SPACING], fill='red', width=2)
            size_label = f"Size: {access_size} bytes"
            draw.text((x + 5, PADDING + 20), size_label, fill='red')
        else:
            # Just draw a line for the access point
            draw.line([x, PADDING, x, HEIGHT-PADDING-INFO_HEIGHT-SPACING], fill='red', width=2)
        
        # Check permissions with priority
        perms = "No Match"
        matching_pmp = None
        for i, entry in enumerate(entries):  # Check from highest priority (lower index)
            perm = entry.check_permission(access_addr, access_size, access_type)
            if perm is not None:
                perms = perm
                matching_pmp = i
                break  # Stop at first match due to priority
        
        # Draw access information
        access_info = f"Access: 0x{access_addr:x}"
        if access_type:
            access_info += f"\nType: {access_type}"
        if matching_pmp is not None:
            access_info += f"\nPMP{matching_pmp}: {perms}"
        else:
            access_info += f"\nPerms: {perms}"
        
        draw.text((x-20, PADDING), access_info, fill='black')
    
    # Draw address scale with fixed intervals
    scale_y = HEIGHT - PADDING - INFO_HEIGHT - SPACING + 20
    num_intervals = 5
    for i in range(num_intervals + 1):
        addr = min_addr + (ADDR_RANGE * i) // num_intervals
        x = PADDING + int((addr - min_addr) * scale)
        draw.line([x, scale_y-5, x, scale_y+5], fill='black')
        draw.text((x-40, scale_y+5), f"0x{addr:08x}", fill='black')
    
    # Save image
    img.save(output_file)

def generate_html_visualization(config: dict, output_file: str) -> None:
    """Generate an interactive HTML visualization of PMP entries."""
    # Read the HTML template
    script_dir = os.path.dirname(os.path.abspath(__file__))
    template_path = os.path.join(script_dir, 'template.html')
    build_dir = ensure_build_dir()
    build_template_path = os.path.join(build_dir, 'template.html')
    
    # Copy template to build directory if needed
    if not os.path.exists(build_template_path) or os.path.getmtime(template_path) > os.path.getmtime(build_template_path):
        with open(template_path, 'r') as src, open(build_template_path, 'w') as dst:
            dst.write(src.read())
    
    with open(build_template_path, 'r') as f:
        template = f.read()
    
    # Convert config to JSON and inject into template
    config_json = json.dumps(config)
    html_content = template.replace('CONFIG_PLACEHOLDER', config_json)
    
    # Write the final HTML
    with open(output_file, 'w') as f:
        f.write(html_content)

def ensure_build_dir():
    """Ensure the build directory exists."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    build_dir = os.path.join(script_dir, 'build')
    os.makedirs(build_dir, exist_ok=True)
    return build_dir

def main():
    parser = argparse.ArgumentParser(description='Visualize PMP entries')
    parser.add_argument('input_yaml', help='Input YAML file')
    parser.add_argument('output_prefix', help='Output filename prefix (will be created in build directory)')
    args = parser.parse_args()

    with open(args.input_yaml, 'r') as f:
        config = yaml.safe_load(f)

    # Parse PMP entries
    entries = []
    for entry in config.get('pmp_entries', []):
        addr = int(entry['addr'], 16)
        cfg = int(entry['cfg'], 16)
        entries.append(PMPEntry(addr=addr, cfg=cfg))

    # Parse access check
    access_addr = None
    access_size = None
    access_type = None
    if 'access_check' in config:
        access_addr = int(config['access_check'], 16)
        access_size = config.get('access_size')
        access_type = config.get('access_type', 'R')  # Default to read access

    # Parse address range
    cacheable_region = config.get('cacheable_region', {})
    min_addr = int(cacheable_region.get('start', '0x80000000'), 16)
    max_addr = int(cacheable_region.get('end', '0x80100000'), 16)

    # Ensure build directory exists and create output path
    build_dir = ensure_build_dir()
    png_output = os.path.join(build_dir, f"{args.output_prefix}.png")

    # Generate PNG visualization
    visualize_pmp_entries(entries, access_addr, access_size, access_type,
                         min_addr, max_addr, png_output)

if __name__ == "__main__":
    main()
