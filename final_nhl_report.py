#!/usr/bin/env python3
"""
Final NHL Report Generator - Working with Real Data
Generates a real NHL report using actual API data
"""

import requests
import json
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
import matplotlib.pyplot as plt
import numpy as np
from io import BytesIO

class FinalNHLReportGenerator:
    def __init__(self):
        self.styles = getSampleStyleSheet()
        self.setup_styles()
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'Mozilla/5.0'})
    
    def setup_styles(self):
        self.title_style = ParagraphStyle(
            'Title',
            parent=self.styles['Heading1'],
            fontSize=24,
            textColor=colors.darkblue,
            alignment=TA_CENTER,
            spaceAfter=20
        )
        
        self.subtitle_style = ParagraphStyle(
            'Subtitle',
            parent=self.styles['Heading2'],
            fontSize=18,
            textColor=colors.darkblue,
            alignment=TA_CENTER,
            spaceAfter=15
        )
        
        self.normal_style = ParagraphStyle(
            'Normal',
            parent=self.styles['Normal'],
            fontSize=11,
            textColor=colors.black,
            spaceAfter=6
        )
    
    def get_team_roster(self, team_code):
        """Get real team roster data"""
        url = f"https://api-web.nhle.com/v1/roster/{team_code}/20242025"
        try:
            response = self.session.get(url, timeout=10)
            if response.status_code == 200:
                return response.json()
            return None
        except:
            return None
    
    def get_team_stats(self, team_code):
        """Get team statistics"""
        roster = self.get_team_roster(team_code)
        if not roster:
            return None
        
        # Analyze roster
        positions = {}
        total_players = len(roster)
        
        for player in roster:
            pos = player.get('position', 'Unknown')
            positions[pos] = positions.get(pos, 0) + 1
        
        return {
            'team': team_code,
            'total_players': total_players,
            'positions': positions,
            'roster': roster
        }
    
    def create_team_comparison_chart(self, team1_stats, team2_stats):
        """Create team comparison chart"""
        if not team1_stats or not team2_stats:
            return None
        
        try:
            fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
            
            # Team 1 roster composition
            team1_positions = team1_stats['positions']
            ax1.pie(team1_positions.values(), labels=team1_positions.keys(), autopct='%1.1f%%', startangle=90)
            ax1.set_title(f'{team1_stats["team"]} Roster Composition')
            
            # Team 2 roster composition
            team2_positions = team2_stats['positions']
            ax2.pie(team2_positions.values(), labels=team2_positions.keys(), autopct='%1.1f%%', startangle=90)
            ax2.set_title(f'{team2_stats["team"]} Roster Composition')
            
            plt.tight_layout()
            
            # Save to BytesIO
            img_buffer = BytesIO()
            plt.savefig(img_buffer, format='png', dpi=300, bbox_inches='tight')
            img_buffer.seek(0)
            plt.close()
            
            return img_buffer
        except Exception as e:
            print(f"Chart creation error: {e}")
            return None
    
    def generate_report(self, team1, team2, output_filename=None):
        """Generate a real NHL report using actual team data"""
        print("🏒 Generating Real NHL Team Report 🏒")
        print("=" * 50)
        
        # Get real team data
        print(f"Fetching {team1} roster...")
        team1_stats = self.get_team_stats(team1)
        
        print(f"Fetching {team2} roster...")
        team2_stats = self.get_team_stats(team2)
        
        if not team1_stats or not team2_stats:
            print("❌ Could not fetch team data")
            return None
        
        # Create output filename
        if not output_filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_filename = f"real_nhl_team_report_{team1}_vs_{team2}_{timestamp}.pdf"
        
        # Create PDF
        doc = SimpleDocTemplate(output_filename, pagesize=letter)
        story = []
        
        # Title
        story.append(Paragraph("🏒 REAL NHL TEAM ANALYSIS REPORT 🏒", self.title_style))
        story.append(Spacer(1, 20))
        
        # Team comparison
        story.append(Paragraph(f"{team1} vs {team2} - Team Analysis", self.subtitle_style))
        story.append(Paragraph(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", self.normal_style))
        story.append(Spacer(1, 20))
        
        # Team stats table
        stats_data = [
            ['Team', 'Total Players', 'Forwards', 'Defensemen', 'Goalies'],
            [team1, 
             team1_stats['total_players'],
             team1_stats['positions'].get('F', 0),
             team1_stats['positions'].get('D', 0),
             team1_stats['positions'].get('G', 0)],
            [team2,
             team2_stats['total_players'],
             team2_stats['positions'].get('F', 0),
             team2_stats['positions'].get('D', 0),
             team2_stats['positions'].get('G', 0)]
        ]
        
        stats_table = Table(stats_data, colWidths=[1.5*inch, 1.5*inch, 1.5*inch, 1.5*inch, 1.5*inch])
        stats_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.darkblue),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ]))
        
        story.append(stats_table)
        story.append(Spacer(1, 20))
        
        # Add team comparison chart
        chart_buffer = self.create_team_comparison_chart(team1_stats, team2_stats)
        if chart_buffer:
            from reportlab.platypus import Image
            img = Image(chart_buffer)
            img.drawHeight = 4*inch
            img.drawWidth = 7*inch
            story.append(img)
            story.append(Spacer(1, 20))
        
        # Team rosters
        story.append(Paragraph(f"{team1} Roster", self.subtitle_style))
        
        # Create roster table for team 1
        roster_data = [['Player Name', 'Position', 'Jersey Number']]
        for player in team1_stats['roster'][:10]:  # First 10 players
            name = player.get('fullName', 'Unknown')
            position = player.get('position', 'Unknown')
            jersey = player.get('jerseyNumber', 'N/A')
            roster_data.append([name, position, jersey])
        
        roster_table = Table(roster_data, colWidths=[3*inch, 1.5*inch, 1.5*inch])
        roster_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.darkred),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
            ('BACKGROUND', (0, 1), (-1, -1), colors.lightgrey),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('ALIGN', (0, 1), (0, -1), 'LEFT'),  # Left align player names
        ]))
        
        story.append(roster_table)
        story.append(Spacer(1, 20))
        
        # Team 2 roster
        story.append(Paragraph(f"{team2} Roster", self.subtitle_style))
        
        roster_data2 = [['Player Name', 'Position', 'Jersey Number']]
        for player in team2_stats['roster'][:10]:  # First 10 players
            name = player.get('fullName', 'Unknown')
            position = player.get('position', 'Unknown')
            jersey = player.get('jerseyNumber', 'N/A')
            roster_data2.append([name, position, jersey])
        
        roster_table2 = Table(roster_data2, colWidths=[3*inch, 1.5*inch, 1.5*inch])
        roster_table2.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.darkgreen),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
            ('BACKGROUND', (0, 1), (-1, -1), colors.lightgreen),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('ALIGN', (0, 1), (0, -1), 'LEFT'),  # Left align player names
        ]))
        
        story.append(roster_table2)
        story.append(Spacer(1, 20))
        
        # Summary
        story.append(Paragraph("Analysis Summary", self.subtitle_style))
        story.append(Paragraph(f"• {team1} has {team1_stats['total_players']} players on their roster", self.normal_style))
        story.append(Paragraph(f"• {team2} has {team2_stats['total_players']} players on their roster", self.normal_style))
        story.append(Paragraph("• This report uses real data from the NHL API", self.normal_style))
        story.append(Paragraph("• All player information is current for the 2024-25 season", self.normal_style))
        
        # Build PDF
        doc.build(story)
        
        print(f"✅ Real NHL team report generated: {output_filename}")
        return output_filename

def main():
    """Generate a real NHL team report"""
    print("🏒 FINAL NHL TEAM REPORT GENERATOR 🏒")
    print("=" * 50)
    
    generator = FinalNHLReportGenerator()
    
    # Use real teams
    team1 = "EDM"  # Edmonton Oilers
    team2 = "FLA"  # Florida Panthers
    
    print(f"Generating team comparison report: {team1} vs {team2}")
    result = generator.generate_report(team1, team2)
    
    if result:
        print(f"🎉 SUCCESS! Real NHL team report created: {result}")
        print("\nThis report contains:")
        print("  • Real team roster data from NHL API")
        print("  • Actual player names and positions")
        print("  • Team composition analysis")
        print("  • Professional PDF layout")
        print("  • Data visualization charts")
        print("  • Current 2024-25 season data")
    else:
        print("❌ Failed to generate report")

if __name__ == "__main__":
    main()
