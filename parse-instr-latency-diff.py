import re
import numpy as np
import matplotlib
matplotlib.use('Agg')  # Fastest backend
import matplotlib.pyplot as plt
import os
import shutil
import argparse
from datetime import datetime
from tqdm import tqdm
from multiprocessing import Pool, cpu_count
from itertools import islice

# Configure plotly for faster rendering
#pio.kaleido.scope.chromium_args = tuple([arg for arg in pio.kaleido.scope.chromium_args if arg != '--no-sandbox'] + ['--single-process'])
#pio.kaleido.scope.default_width = 1200
#pio.kaleido.scope.default_height = 800
#pio.kaleido.scope.default_scale = 0.8  # Reduce quality slightly for faster saving

def clean_build_dir():
    # Get build directory path
    build_dir = os.path.join(os.path.dirname(__file__), 'build')
    # Remove if exists
    if os.path.exists(build_dir):
        shutil.rmtree(build_dir)
    # Create fresh build directory
    os.makedirs(build_dir)
    return build_dir

def process_match(args):
    try:
        i, old_match, new_match = args
        old_time = int(old_match[1])
        new_time = int(new_match[1])
        time_diff = (old_time - new_time) // 10  # Integer division for cycles
        return (old_match[2], time_diff)  # Return (PC, time_diff)
    except Exception as e:
        return None

def chunk_list(lst, chunk_size):
    """Yield successive chunks from lst."""
    for i in range(0, len(lst), chunk_size):
        yield list(islice(lst, i, i + chunk_size))

def format_pc(pc):
    # First remove 0x and leading zeros
    pc = pc.lower()  # Convert to lowercase for consistency
    if pc.startswith('0x'):
        pc = pc[2:]  # Remove '0x' prefix
        # Remove first 8 zeros if they exist
        if len(pc) >= 8 and pc[:8] == '00000000':
            pc = pc[8:]
        # Find first non-zero byte
        for i in range(0, len(pc)-4, 2):
            if pc[i:i+2] != '00':
                first_byte = pc[i:i+2]
                break
        else:
            first_byte = '00'
        return f"0x{first_byte}..{pc[-4:]}"
    return pc  # Return as is if not hex

def main():
    try:
        # Parse command line arguments
        parser = argparse.ArgumentParser(description='Analyze instruction latency changes from diff file')
        parser.add_argument('diff_file', help='Path to the diff file')
        parser.add_argument('--processes', type=int, default=max(1, cpu_count() - 1),
                          help='Number of processes to use (default: number of CPU cores - 1)')
        parser.add_argument('--top', type=int, default=5,
                          help='Number of top peaks to display (default: 5)')
        args = parser.parse_args()

        # Clean and recreate build directory
        print("Cleaning build directory...")
        build_dir = clean_build_dir()

        # Validate input file
        if not os.path.exists(args.diff_file):
            print(f"Error: File {args.diff_file} does not exist")
            exit(1)

        try:
            print("Reading diff file...")
            with open(args.diff_file) as the_file:
                all_lines = the_file.readlines()

            print("Processing diff file...")
            old_line_pattern = r'([\-])\[\s+(\d+)\]core\s+\d:\s[0-9]\s(?P<addr>[0-9abcdefx]+)\s\((?P<instr>[0-9abcdefx]+)\)'
            new_line_pattern = r'([\+])\[\s+(\d+)\]core\s+\d:\s[0-9]\s(?P<addr>[0-9abcdefx]+)\s\((?P<instr>[0-9abcdefx]+)\)'
            
            content = "".join(all_lines)
            print("Finding matches...")
            all_old_matches = re.findall(old_line_pattern, content)
            all_new_matches = re.findall(new_line_pattern, content)

            if not all_old_matches or not all_new_matches:
                print("Error: No matches found in diff file")
                exit(1)

            print(f"Found {len(all_old_matches)} pairs of changes")

            # Generate timestamp for unique filenames
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            # Process matches in parallel
            print(f"Analyzing changes using {args.processes} processes...")
            with Pool(processes=args.processes) as pool:
                # Create list of arguments for each process
                process_args = [(i, old, new) for i, (old, new) in enumerate(zip(all_old_matches, all_new_matches))]
                
                # Process in chunks to show progress
                chunk_size = max(1000, len(process_args) // (args.processes * 10))
                chunks = list(chunk_list(process_args, chunk_size))
                
                results = []
                with tqdm(total=len(process_args), desc="Processing instructions") as pbar:
                    for chunk in chunks:
                        chunk_results = pool.map(process_match, chunk)
                        results.extend(chunk_results)
                        pbar.update(len(chunk))

            # Filter out None results and split into separate lists
            valid_results = [r for r in results if r is not None]
            if not valid_results:
                print("Error: No valid changes found")
                exit(1)

            pc_addrs, pc_changes = zip(*valid_results)

            print("Calculating statistics...")
            # Calculate statistics
            threshold = 5  # 5 cycles
            
            print("Creating visualization...")
            
            # Filter out small changes and find canceling pairs
            change_counts = {}
            significant_indices = []
            cancelled_pairs = []
            processed_indices = set()  # Track which indices we've already handled
            
            i = 0
            while i < len(pc_changes):
                if i in processed_indices:
                    i += 1
                    continue
                    
                # Look ahead up to 5 instructions to find canceling changes
                found_cancel = False
                current_change = pc_changes[i]
                for j in range(i + 1, min(i + 6, len(pc_changes))):  # Look up to 5 instructions ahead
                    if pc_changes[j] + current_change == 0:
                        # Found canceling pair
                        cancelled_pairs.append((pc_addrs[i], pc_addrs[j], current_change, j - i))
                        processed_indices.add(i)
                        processed_indices.add(j)
                        found_cancel = True
                        i = j + 1  # Skip to after the canceling instruction
                        break
                
                if not found_cancel:
                    if abs(current_change) >= 5:  # Keep all changes >= 5 cycles
                        significant_indices.append(i)
                    else:
                        # Count occurrences of each small change
                        change_counts[current_change] = change_counts.get(current_change, 0) + 1
                    i += 1
            
            # Get data for plotting
            plot_indices = significant_indices
            plot_changes = [pc_changes[i] for i in plot_indices]
            plot_pcs = [pc_addrs[i] for i in plot_indices]
            
            # Group duplicate changes and count occurrences
            change_groups = {}
            pc_groups = {}
            for i, change in enumerate(plot_changes):
                if change not in change_groups:
                    change_groups[change] = 1
                    pc_groups[change] = [plot_pcs[i]]
                else:
                    change_groups[change] += 1
                    pc_groups[change].append(plot_pcs[i])
            
            # Create sorted list of unique changes and their counts
            unique_changes = sorted(change_groups.keys(), key=abs, reverse=True)
            plot_counts = [change_groups[c] for c in unique_changes]
            scaled_changes = [c * count for c, count in zip(unique_changes, plot_counts)]
            
            # Get representative PC for each change (first one in group)
            representative_pcs = [pc_groups[c][0] for c in unique_changes]
            formatted_pcs = [format_pc(pc) for pc in representative_pcs]
            
            # Create plot with better quality
            plt.figure(figsize=(12, 8), dpi=150)
            
            # Create bars with colors
            colors = ['#FF0000' if change > 0 else '#00CC00' for change in unique_changes]
            bars = plt.bar(range(len(unique_changes)), [-c for c in scaled_changes], color=colors, 
                         edgecolor='black', linewidth=0.5)
            
            # Create summary of skipped changes
            skipped_summary = []
            for change, count in sorted(change_counts.items(), key=lambda x: abs(x[0]), reverse=True):
                if count > 1:  # Only show in summary if multiple PCs had this change
                    skipped_summary.append(f"{count} PCs: {change:+d} cycles")
            
            # Calculate total potential improvement from cancelled pairs
            total_potential_improvement = sum(abs(change) for pc1, pc2, change, distance in cancelled_pairs if change < 0)
            
            # Add styling
            title = 'Instruction Latency Changes (Bar Height = Count × Change)\nGreen: Improved (decreased), Red: Degraded (increased)'
            if skipped_summary:
                title += '\nSkipped small changes: ' + ' | '.join(skipped_summary)
            if cancelled_pairs:
                title += f'\nSkipped {len(cancelled_pairs)} canceling PC pairs (potentially {total_potential_improvement} cycles)'
            
            plt.title(title, pad=10, fontsize=10)
            plt.xlabel('Program Counter', fontsize=10)
            plt.ylabel('Scaled Latency Change (cycles × count)', fontsize=10)
            
            # Use formatted PC values for x-axis labels
            plt.xticks(range(len(unique_changes)), 
                      formatted_pcs,
                      rotation=45,
                      ha='right',
                      fontsize=8)
            
            # Add value labels on top/bottom of bars showing both change and count
            for i, bar in enumerate(bars):
                height = bar.get_height()
                change = unique_changes[i]
                count = plot_counts[i]
                plt.text(bar.get_x() + bar.get_width()/2, 
                        -scaled_changes[i] + (1 if change < 0 else -1),
                        f'{abs(change)}×{count}',
                        ha='center', va='bottom' if change < 0 else 'top',
                        fontsize=8)
            
            # Minimal grid for readability
            plt.grid(True, axis='y', linestyle=':', alpha=0.3)
            plt.tight_layout()

            # Save outputs
            base_name = os.path.splitext(os.path.basename(args.diff_file))[0]
            output_base = f"{base_name}_{timestamp}"
            
            print("\nSaving outputs...")
            
            # Pre-compute stats string for faster writing
            stats_lines = [
                "Latency Change Statistics (in cycles)",
                "=" * 40,
                "",
                f"Total instructions analyzed: {len(pc_changes)}",
                f"Maximum positive change: {max(pc_changes)}",
                f"Maximum negative change: {min(pc_changes)}",
                f"Standard deviation of changes: {int(np.std(pc_changes))}",
                "",
                "Plotted Changes (grouped by magnitude):",
                "-" * 40
            ]
            
            # Add plotted changes first
            for i, change in enumerate(unique_changes):
                count = change_groups[change]
                pcs = pc_groups[change]
                stats_lines.append(f"Bar #{i+1}: {change:+d} cycles × {count} occurrences")
                stats_lines.append(f"  Representative PC (plotted): {format_pc(pcs[0])} (full: {pcs[0]})")
                if len(pcs) > 1:
                    stats_lines.append("  Other PCs with same change:")
                    for j, pc in enumerate(pcs[1:], 1):
                        stats_lines.append(f"    {j}. {format_pc(pc)} (full: {pc})")
                stats_lines.append("")
            
            stats_lines.extend([
                "Canceling PC pairs (within 5 instructions):",
                "-" * 40
            ])
            
            # Add canceling pairs information with distance
            for i, (pc1, pc2, change, distance) in enumerate(cancelled_pairs):
                stats_lines.append(f"Pair #{i+1}: {format_pc(pc1)} ({change:+d}) and {format_pc(pc2)} ({-change:+d}) - {distance} instr apart")
                stats_lines.append(f"         Full PCs: {pc1} and {pc2}")
            
            stats_lines.extend([
                "",
                "All changes by magnitude:",
                "-" * 40
            ])
            
            # Add all changes
            all_sorted = sorted(zip(pc_addrs, pc_changes), key=lambda x: abs(x[1]), reverse=True)
            stats_lines.extend([f"PC: {format_pc(pc)} (full: {pc}), Change: {change:+d}" for pc, change in all_sorted])
            
            stats_content = "\n".join(stats_lines)
            
            # Save both files
            img_path = os.path.join(build_dir, f"{output_base}.png")
            stats_path = os.path.join(build_dir, f"{output_base}_stats.txt")
            
            # Save image with better quality
            plt.savefig(img_path, dpi=150, bbox_inches='tight', pad_inches=0.2)
            plt.close()
            
            # Write stats file efficiently
            with open(stats_path, 'w') as f:
                f.write(stats_content)

            print(f"\nOutputs saved in {build_dir}:")
            print(f"- Static image: {os.path.basename(img_path)}")
            print(f"- Full statistics: {os.path.basename(stats_path)}")

        except Exception as e:
            print(f"Error: {str(e)}")
            exit(1)

    except Exception as e:
        print(f"Error: {str(e)}")
        exit(1)

if __name__ == "__main__":
    main()
