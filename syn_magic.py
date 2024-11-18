'''
    Author: Karthik B K <karthik.bk@incoresemi.com>
    Created on: 2024 November 18

    Many thanks to Claude 3.5 Sonnet for all the help.
    "embrace ai. resistance is futile."
    
    This script parses and visualizes synthesis area and timing reports using interactive visualizations.
'''

import sys
import os
import re
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import argparse

class AreaReportParser:
    def __init__(self, report_path):
        self.report_path = report_path
        self.data = []
        
    def parse_report(self):
        with open(self.report_path, 'r') as f:
            lines = f.readlines()
            
        # Skip header until we find the line with Instance
        start_idx = 0
        for i, line in enumerate(lines):
            if 'Instance' in line and 'Module' in line and 'Cell Count' in line:
                start_idx = i + 2  # Skip the separator line
                break
                
        current_indent = 0
        path_stack = []
        
        for line in lines[start_idx:]:
            if not line.strip() or '----' in line:
                continue
                
            # Split the line while preserving whitespace at the start
            instance_info = line.split()
            if not instance_info:
                continue
                
            # Calculate indentation level
            indent = len(line) - len(line.lstrip())
            instance_name = instance_info[0]
            
            # Handle module hierarchy
            while indent <= current_indent and path_stack:
                path_stack.pop()
                current_indent -= 2
                
            path_stack.append(instance_name)
            current_indent = indent
            
            try:
                # Extract relevant information
                module_name = instance_info[1] if len(instance_info) > 1 else ""
                
                # Find indices for numeric values
                cell_count = 0
                total_area = 0
                
                for idx, val in enumerate(instance_info[2:], start=2):
                    try:
                        if '.' in val:  # Look for area value (float)
                            total_area = float(val)
                        elif val.isdigit():  # Look for cell count (integer)
                            cell_count = int(val)
                    except ValueError:
                        continue
                
                self.data.append({
                    'id': '/'.join(path_stack),
                    'parent': '/'.join(path_stack[:-1]),
                    'name': instance_name,
                    'module': module_name,
                    'cell_count': cell_count,
                    'total_area': total_area
                })
            except Exception as e:
                print(f"Warning: Could not parse line: {line.strip()}")
                continue

class TimingReportParser:
    def __init__(self, report_path):
        self.report_path = report_path
        self.data = []
        
    def parse_report(self):
        with open(self.report_path, 'r') as f:
            lines = f.readlines()
            
        # Skip header until we find the line with Slack
        start_idx = 0
        for i, line in enumerate(lines):
            if 'Slack' in line and 'Endpoint' in line and 'Cost Group' in line:
                start_idx = i + 2  # Skip the separator line
                break
                
        for line in lines[start_idx:]:
            if not line.strip() or '----' in line:
                continue
                
            # Split the line while preserving whitespace
            parts = line.strip().split(None, 2)
            if len(parts) < 2:
                continue
                
            try:
                slack = float(parts[0].replace('ps', ''))  # Remove 'ps' and convert to float
                endpoint = parts[1]
                cost_group = parts[2] if len(parts) > 2 else ""
                
                # Extract module name from endpoint path
                path_parts = endpoint.split('/')
                if len(path_parts) >= 2:
                    # Use first two parts of the path as module
                    module = '/'.join(path_parts[:2])
                else:
                    # Use the entire path if it's just one level
                    module = endpoint
                
                # Clean up register arrays from module name
                module = re.sub(r'\[[0-9]+\]', '', module)
                
                self.data.append({
                    'slack': slack,
                    'endpoint': endpoint,
                    'cost_group': cost_group,
                    'module': module
                })
            except Exception as e:
                print(f"Warning: Could not parse line: {line.strip()}")
                continue

def visualize_area_report(area_path, timing_path=None, output_path=None):
    """
    Parse and visualize synthesis area and timing reports.
    
    Args:
        area_path (str): Path to the area report file
        timing_path (str, optional): Path to the timing report file
        output_path (str, optional): Path to save the HTML output. If None, will use the report path with .html extension
    """
    # Check if area report exists
    if not os.path.isfile(area_path):
        print(f"Error: Area report not found at {area_path}")
        sys.exit(1)
        
    # Check if timing report exists if provided
    if timing_path and not os.path.isfile(timing_path):
        print(f"Error: Timing report not found at {timing_path}")
        sys.exit(1)

    if output_path is None:
        output_path = area_path.rsplit('.', 1)[0] + '_visualization.html'

    # Parse area report
    area_parser = AreaReportParser(area_path)
    area_parser.parse_report()
    df_area = pd.DataFrame(area_parser.data)
    
    # Create area treemap
    area_fig = px.treemap(
        df_area,
        ids='id',
        names='name',
        parents='parent',
        values='total_area',
        custom_data=['module', 'cell_count'],
        hover_data=['module', 'cell_count', 'total_area'],
        title='Area Distribution'
    )

    # Parse timing report if provided
    if timing_path:
        timing_parser = TimingReportParser(timing_path)
        timing_parser.parse_report()
        df_timing = pd.DataFrame(timing_parser.data)
        
        # Create timing violin plot
        timing_fig = go.Figure()
        
        # Group data by module and calculate statistics
        module_stats = df_timing.groupby('module').agg({
            'slack': ['count', 'mean', 'min', 'max']
        }).sort_values(('slack', 'count'), ascending=False)
        
        # Select top N modules by endpoint count
        top_n_modules = 10
        main_modules = module_stats.head(top_n_modules).index
        
        # Create "Others" category for remaining modules
        df_timing['module_group'] = df_timing['module'].apply(
            lambda x: x if x in main_modules else 'Others'
        )
        
        # Create a color scale for modules
        unique_modules = sorted(df_timing['module_group'].unique())
        colors = px.colors.qualitative.Set3[:len(unique_modules)]
        module_colors = dict(zip(unique_modules, colors))
        
        # Add violin plots for each module with consistent colors
        for module in unique_modules:
            module_data = df_timing[df_timing['module_group'] == module]
            display_name = module.split('/')[-1] if '/' in module else module
            
            timing_fig.add_trace(go.Violin(
                x=[display_name] * len(module_data),
                y=module_data['slack'],
                name=display_name,
                box_visible=True,
                meanline_visible=True,
                points='all',
                fillcolor=module_colors[module],
                line_color=module_colors[module]
            ))
        
        timing_fig.update_layout(
            title='Timing Slack Distribution by Module',
            xaxis_title='Module',
            yaxis_title='Slack (ps)',
            showlegend=True,
            legend_title_text='Modules'
        )
        
        # Create a new figure with subplots
        fig = make_subplots(
            rows=1, cols=2,
            subplot_titles=('Area Distribution', 'Timing Distribution by Module'),
            specs=[[{'type': 'treemap'}, {'type': 'violin'}]],
            horizontal_spacing=0.02,
            vertical_spacing=0.1  # Add vertical spacing for titles
        )
        
        # Add traces from both figures
        for trace in area_fig.data:
            fig.add_trace(trace, row=1, col=1)
        for trace in timing_fig.data:
            fig.add_trace(trace, row=1, col=2)
        
        # Update layout
        fig.update_layout(
            template='plotly_dark',
            paper_bgcolor='rgb(17, 17, 17)',
            plot_bgcolor='rgb(17, 17, 17)',
            font=dict(color='white'),
            width=2400,
            height=800,
            title_font_size=20,
            margin=dict(t=100, l=25, r=25, b=25),  # Increased top margin
            showlegend=True,
            legend=dict(
                yanchor="top",
                y=0.99,
                xanchor="left",
                x=0.55,
                bgcolor='rgba(17, 17, 17, 0.5)',
                bordercolor='white',
                borderwidth=1
            )
        )
        
        # Update x and y axis labels for timing plot
        fig.update_xaxes(title_text="Module", row=1, col=2)
        fig.update_yaxes(title_text="Slack (ps)", row=1, col=2)
    else:
        fig = area_fig
        fig.update_layout(
            template='plotly_dark',
            paper_bgcolor='rgb(17, 17, 17)',
            plot_bgcolor='rgb(17, 17, 17)',
            font=dict(color='white'),
            width=2400,
            height=800,
            title_font_size=20,
            margin=dict(t=100, l=25, r=25, b=25),  # Increased top margin
        )
    
    # Write to HTML with custom styling
    html_content = f'''
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Synthesis Report Visualization</title>
        <style>
            body {{
                margin: 0;
                padding: 0;
                background-color: rgb(17, 17, 17);
                display: flex;
                flex-direction: column;
                align-items: center;
                min-height: 100vh;
            }}
            #plotly-div {{
                margin: auto;
                width: 100%;
                max-width: {fig.layout.width}px;
            }}
            .file-paths {{
                color: white;
                font-family: monospace;
                margin: 20px;
                padding: 15px;
                background-color: rgba(255, 255, 255, 0.1);
                border-radius: 5px;
                width: 90%;
                max-width: {fig.layout.width}px;
            }}
            .file-paths h3 {{
                margin-top: 0;
                margin-bottom: 10px;
            }}
            .file-path {{
                margin: 5px 0;
                word-break: break-all;
            }}
        </style>
    </head>
    <body>
        <div class="file-paths">
            <h3>Input Files:</h3>
            <div class="file-path">Area Report: {area_path}</div>
            {'<div class="file-path">Timing Endpoints: ' + timing_path + '</div>' if timing_path else ''}
        </div>
        <div id="plotly-div">
            {fig.to_html(full_html=False, include_plotlyjs=True, config={'responsive': True})}
        </div>
    </body>
    </html>
    '''
    
    with open(output_path, 'w') as f:
        f.write(html_content)
    
    print(f"Visualization saved to: {output_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Visualize synthesis area and timing reports')
    parser.add_argument('area_report', help='Path to the area report file')
    parser.add_argument('--timing_report', help='Path to the timing report file (optional)')
    args = parser.parse_args()
    
    visualize_area_report(args.area_report, args.timing_report)