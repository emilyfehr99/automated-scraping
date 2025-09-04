#!/usr/bin/env python3
"""
Enhanced NHL Report Generator - 2025 Edition
Comprehensive report generator with all advanced features
"""

from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.graphics.shapes import Drawing, String
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.charts.legends import Legend
import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd
import numpy as np
from io import BytesIO
import os
from datetime import datetime
from typing import Dict, List, Optional, Any
from enhanced_nhl_api_client import EnhancedNHLAPIClient
from nhl_advanced_analytics import NHLAdvancedAnalytics

class EnhancedNHLReportGenerator:
    def __init__(self):
        """Initialize the enhanced NHL report generator"""
        self.styles = getSampleStyleSheet()
        self.setup_custom_styles()
        self.api_client = EnhancedNHLAPIClient()
        self.analytics = NHLAdvancedAnalytics()
        
        # Team colors for visualizations
        self.team_colors = {
            'EDM': '#FF4C00', 'FLA': '#C8102E', 'BOS': '#FFB81C', 'TOR': '#003E7E',
            'MTL': '#AF1E2D', 'OTT': '#C52032', 'BUF': '#002654', 'DET': '#CE1126',
            'TBL': '#002868', 'CAR': '#CC0000', 'WSH': '#C8102E', 'PIT': '#000000',
            'NYR': '#0038A8', 'NYI': '#00539B', 'NJD': '#CE1126', 'PHI': '#F74902',
            'CBJ': '#002654', 'NSH': '#FFB81C', 'STL': '#002F87', 'MIN': '#154734',
            'WPG': '#041E42', 'COL': '#6F263D', 'ARI': '#8C2633', 'VGK': '#B4975A',
            'SJS': '#006D75', 'LAK': '#111111', 'ANA': '#F47A20', 'CGY': '#C8102E',
            'VAN': '#001F5C', 'SEA': '#001628', 'CHI': '#C8102E', 'DAL': '#006847'
        }
    
    def setup_custom_styles(self):
        """Setup custom paragraph styles for the enhanced report"""
        # Enhanced title style
        self.title_style = ParagraphStyle(
            'EnhancedTitle',
            parent=self.styles['Heading1'],
            fontSize=28,
            textColor=colors.darkblue,
            alignment=TA_CENTER,
            spaceAfter=25,
            fontName='Helvetica-Bold'
        )
        
        # Enhanced subtitle style
        self.subtitle_style = ParagraphStyle(
            'EnhancedSubtitle',
            parent=self.styles['Heading2'],
            fontSize=20,
            textColor=colors.darkblue,
            alignment=TA_CENTER,
            spaceAfter=18,
            fontName='Helvetica-Bold'
        )
        
        # Section header style
        self.section_style = ParagraphStyle(
            'EnhancedSection',
            parent=self.styles['Heading3'],
            fontSize=16,
            textColor=colors.darkred,
            alignment=TA_LEFT,
            spaceAfter=12,
            fontName='Helvetica-Bold'
        )
        
        # Subsection style
        self.subsection_style = ParagraphStyle(
            'EnhancedSubsection',
            parent=self.styles['Heading4'],
            fontSize=14,
            textColor=colors.darkgreen,
            alignment=TA_LEFT,
            spaceAfter=8,
            fontName='Helvetica-Bold'
        )
        
        # Normal text style
        self.normal_style = ParagraphStyle(
            'EnhancedNormal',
            parent=self.styles['Normal'],
            fontSize=11,
            textColor=colors.black,
            alignment=TA_LEFT,
            spaceAfter=6,
            fontName='Helvetica'
        )
        
        # Stat text style
        self.stat_style = ParagraphStyle(
            'EnhancedStat',
            parent=self.styles['Normal'],
            fontSize=12,
            textColor=colors.darkgreen,
            alignment=TA_LEFT,
            spaceAfter=4,
            fontName='Helvetica-Bold'
        )
        
        # Highlight style
        self.highlight_style = ParagraphStyle(
            'EnhancedHighlight',
            parent=self.styles['Normal'],
            fontSize=12,
            textColor=colors.darkblue,
            alignment=TA_LEFT,
            spaceAfter=6,
            fontName='Helvetica-Bold'
        )
    
    def create_enhanced_title_page(self, game_data: Dict) -> List:
        """Create an enhanced title page with game context"""
        story = []
        
        # Main title
        story.append(Paragraph("🏒 ENHANCED NHL POST-GAME REPORT 🏒", self.title_style))
        story.append(Spacer(1, 20))
        
        # Game info
        game_info = game_data['game_center']['game']
        away_team = game_data['game_center']['awayTeam']
        home_team = game_data['game_center']['homeTeam']
        
        # Game header with enhanced styling
        story.append(Paragraph(f"{away_team['abbrev']} vs {home_team['abbrev']}", self.subtitle_style))
        story.append(Paragraph(f"Final Score: {away_team['abbrev']} {game_info['awayTeamScore']} - {home_team['abbrev']} {game_info['homeTeamScore']}", self.highlight_style))
        
        # Game details
        story.append(Spacer(1, 15))
        story.append(Paragraph(f"<b>Date:</b> {game_info['gameDate']}", self.normal_style))
        story.append(Paragraph(f"<b>Venue:</b> {game_data['game_center'].get('venue', {}).get('default', 'Unknown Arena')}", self.normal_style))
        story.append(Paragraph(f"<b>Game Type:</b> Stanley Cup Finals", self.normal_style))
        
        # Add standings context if available
        if 'standings' in game_data and game_data['standings']:
            story.append(Spacer(1, 10))
            story.append(Paragraph("📊 STANDINGS CONTEXT", self.section_style))
            self._add_standings_context(story, game_data['standings'], away_team['abbrev'], home_team['abbrev'])
        
        story.append(PageBreak())
        return story
    
    def create_enhanced_score_summary(self, game_data: Dict) -> List:
        """Create enhanced score summary with period analysis"""
        story = []
        
        story.append(Paragraph("📈 ENHANCED SCORE SUMMARY", self.subtitle_style))
        story.append(Spacer(1, 15))
        
        game_info = game_data['game_center']['game']
        away_team = game_data['game_center']['awayTeam']
        home_team = game_data['game_center']['homeTeam']
        
        # Enhanced score table with more details
        score_data = [
            ['', '1st', '2nd', '3rd', 'OT', 'Total', 'Shots', 'PP%'],
            [away_team['abbrev'], 
             game_info['awayTeamScoreByPeriod'][0] if len(game_info['awayTeamScoreByPeriod']) > 0 else 0,
             game_info['awayTeamScoreByPeriod'][1] if len(game_info['awayTeamScoreByPeriod']) > 1 else 0,
             game_info['awayTeamScoreByPeriod'][2] if len(game_info['awayTeamScoreByPeriod']) > 2 else 0,
             game_info['awayTeamScoreByPeriod'][3] if len(game_info['awayTeamScoreByPeriod']) > 3 else 0,
             game_info['awayTeamScore'],
             game_data['boxscore']['awayTeam'].get('sog', 'N/A'),
             f"{game_data['boxscore']['awayTeam'].get('powerPlayConversion', 'N/A')}"],
            [home_team['abbrev'],
             game_info['homeTeamScoreByPeriod'][0] if len(game_info['homeTeamScoreByPeriod']) > 0 else 0,
             game_info['homeTeamScoreByPeriod'][1] if len(game_info['homeTeamScoreByPeriod']) > 1 else 0,
             game_info['homeTeamScoreByPeriod'][2] if len(game_info['homeTeamScoreByPeriod']) > 2 else 0,
             game_info['homeTeamScoreByPeriod'][3] if len(game_info['homeTeamScoreByPeriod']) > 3 else 0,
             game_info['homeTeamScore'],
             game_data['boxscore']['homeTeam'].get('sog', 'N/A'),
             f"{game_data['boxscore']['homeTeam'].get('powerPlayConversion', 'N/A')}"]
        ]
        
        score_table = Table(score_data, colWidths=[1.2*inch, 0.7*inch, 0.7*inch, 0.7*inch, 0.7*inch, 0.8*inch, 0.8*inch, 0.8*inch])
        score_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.darkblue),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 11),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
        ]))
        
        story.append(score_table)
        story.append(Spacer(1, 20))
        
        # Add period analysis
        story.append(Paragraph("🎯 PERIOD ANALYSIS", self.section_style))
        self._add_period_analysis(story, game_info, away_team, home_team)
        
        return story
    
    def create_advanced_player_analytics(self, game_data: Dict) -> List:
        """Create advanced player analytics section"""
        story = []
        
        story.append(Paragraph("⭐ ADVANCED PLAYER ANALYTICS", self.subtitle_style))
        story.append(Spacer(1, 15))
        
        # Get player stats from boxscore
        boxscore = game_data['boxscore']
        away_players = boxscore.get('awayTeam', {}).get('players', [])
        home_players = boxscore.get('homeTeam', {}).get('players', [])
        
        # Top performers analysis
        story.append(Paragraph("🏆 TOP PERFORMERS", self.section_style))
        self._add_top_performers(story, away_players + home_players)
        
        # Player comparison
        story.append(Paragraph("⚖️ KEY PLAYER COMPARISONS", self.section_style))
        self._add_player_comparisons(story, away_players, home_players)
        
        # Advanced metrics
        story.append(Paragraph("📊 ADVANCED METRICS", self.section_style))
        self._add_advanced_metrics(story, game_data)
        
        return story
    
    def create_play_by_play_analysis(self, game_data: Dict) -> List:
        """Create detailed play-by-play analysis"""
        story = []
        
        story.append(Paragraph("🎬 PLAY-BY-PLAY ANALYSIS", self.subtitle_style))
        story.append(Spacer(1, 15))
        
        if 'play_by_play' in game_data and game_data['play_by_play']:
            play_data = game_data['play_by_play']
            
            # Key moments
            story.append(Paragraph("🔑 KEY MOMENTS", self.section_style))
            self._add_key_moments(story, play_data)
            
            # Momentum analysis
            story.append(Paragraph("📈 MOMENTUM ANALYSIS", self.section_style))
            self._add_momentum_analysis(story, play_data)
            
            # Shot analysis
            story.append(Paragraph("🎯 SHOT ANALYSIS", self.section_style))
            self._add_shot_analysis(story, play_data)
        else:
            story.append(Paragraph("Play-by-play data not available for this game.", self.normal_style))
        
        return story
    
    def create_enhanced_visualizations(self, game_data: Dict) -> List:
        """Create enhanced visualizations using the analytics engine"""
        story = []
        
        story.append(Paragraph("📊 ENHANCED VISUALIZATIONS", self.subtitle_style))
        story.append(Spacer(1, 15))
        
        try:
            # Team comparison dashboard
            if 'play_by_play' in game_data and game_data['play_by_play']:
                fig = self.analytics.create_team_comparison_dashboard(
                    game_data['boxscore']['awayTeam'],
                    game_data['boxscore']['homeTeam']
                )
                if fig:
                    img_buffer = BytesIO()
                    fig.savefig(img_buffer, format='png', dpi=300, bbox_inches='tight')
                    img_buffer.seek(0)
                    
                    img = Image(img_buffer)
                    img.drawHeight = 6*inch
                    img.drawWidth = 8*inch
                    story.append(img)
                    story.append(Spacer(1, 15))
                    plt.close(fig)
            
            # Momentum chart
            if 'play_by_play' in game_data and game_data['play_by_play']:
                fig = self.analytics.create_momentum_chart(game_data['play_by_play'])
                if fig:
                    img_buffer = BytesIO()
                    fig.savefig(img_buffer, format='png', dpi=300, bbox_inches='tight')
                    img_buffer.seek(0)
                    
                    img = Image(img_buffer)
                    img.drawHeight = 4*inch
                    img.drawWidth = 7*inch
                    story.append(img)
                    story.append(Spacer(1, 15))
                    plt.close(fig)
            
            # Shot heatmaps
            away_team = game_data['game_center']['awayTeam']['abbrev']
            home_team = game_data['game_center']['homeTeam']['abbrev']
            
            if 'play_by_play' in game_data and game_data['play_by_play']:
                # Away team heatmap
                fig = self.analytics.create_shot_heatmap(game_data['play_by_play'], away_team)
                if fig:
                    img_buffer = BytesIO()
                    fig.savefig(img_buffer, format='png', dpi=300, bbox_inches='tight')
                    img_buffer.seek(0)
                    
                    img = Image(img_buffer)
                    img.drawHeight = 4*inch
                    img.drawWidth = 6*inch
                    story.append(img)
                    story.append(Spacer(1, 10))
                    plt.close(fig)
                
                # Home team heatmap
                fig = self.analytics.create_shot_heatmap(game_data['play_by_play'], home_team)
                if fig:
                    img_buffer = BytesIO()
                    fig.savefig(img_buffer, format='png', dpi=300, bbox_inches='tight')
                    img_buffer.seek(0)
                    
                    img = Image(img_buffer)
                    img.drawHeight = 4*inch
                    img.drawWidth = 6*inch
                    story.append(img)
                    story.append(Spacer(1, 15))
                    plt.close(fig)
            
        except Exception as e:
            story.append(Paragraph(f"Visualization error: {str(e)}", self.normal_style))
        
        return story
    
    def create_goalie_analysis(self, game_data: Dict) -> List:
        """Create comprehensive goalie analysis"""
        story = []
        
        story.append(Paragraph("🥅 GOALIE PERFORMANCE ANALYSIS", self.subtitle_style))
        story.append(Spacer(1, 15))
        
        # Get goalie stats
        boxscore = game_data['boxscore']
        away_goalies = []
        home_goalies = []
        
        for player in boxscore.get('awayTeam', {}).get('players', []):
            if player.get('position', '').upper() == 'G':
                away_goalies.append(player)
        
        for player in boxscore.get('homeTeam', {}).get('players', []):
            if player.get('position', '').upper() == 'G':
                home_goalies.append(player)
        
        # Create goalie performance charts
        for goalie in away_goalies + home_goalies:
            try:
                fig = self.analytics.create_goalie_performance_chart(goalie)
                if fig:
                    img_buffer = BytesIO()
                    fig.savefig(img_buffer, format='png', dpi=300, bbox_inches='tight')
                    img_buffer.seek(0)
                    
                    img = Image(img_buffer)
                    img.drawHeight = 5*inch
                    img.drawWidth = 7*inch
                    story.append(img)
                    story.append(Spacer(1, 15))
                    plt.close(fig)
            except Exception as e:
                story.append(Paragraph(f"Goalie chart error: {str(e)}", self.normal_style))
        
        return story
    
    def _add_standings_context(self, story: List, standings_data: Dict, team1: str, team2: str):
        """Add standings context to the report"""
        # This would extract and display relevant standings information
        story.append(Paragraph(f"Current standings context for {team1} vs {team2}", self.normal_style))
    
    def _add_period_analysis(self, story: List, game_info: Dict, away_team: Dict, home_team: Dict):
        """Add detailed period analysis"""
        away_periods = game_info.get('awayTeamScoreByPeriod', [])
        home_periods = game_info.get('homeTeamScoreByPeriod', [])
        
        for i, (away_goals, home_goals) in enumerate(zip(away_periods, home_periods)):
            period_name = f"Period {i+1}"
            if i == 3:
                period_name = "Overtime"
            
            story.append(Paragraph(f"<b>{period_name}:</b> {away_team['abbrev']} {away_goals} - {home_team['abbrev']} {home_goals}", self.normal_style))
    
    def _add_top_performers(self, story: List, players: List):
        """Add top performers analysis"""
        # Sort players by points
        players_with_stats = []
        for player in players:
            stats = player.get('stats', {})
            points = stats.get('goals', 0) + stats.get('assists', 0)
            if points > 0:
                players_with_stats.append((player, points))
        
        players_with_stats.sort(key=lambda x: x[1], reverse=True)
        
        if players_with_stats:
            story.append(Paragraph("Top Point Scorers:", self.subsection_style))
            for player, points in players_with_stats[:5]:
                name = player.get('name', 'Unknown')
                team = player.get('team', {}).get('abbrev', 'Unknown')
                goals = player.get('stats', {}).get('goals', 0)
                assists = player.get('stats', {}).get('assists', 0)
                story.append(Paragraph(f"• {name} ({team}): {goals}G, {assists}A, {points}P", self.normal_style))
    
    def _add_player_comparisons(self, story: List, away_players: List, home_players: List):
        """Add player comparison analysis"""
        # This would implement detailed player comparisons
        story.append(Paragraph("Player comparison analysis would go here", self.normal_style))
    
    def _add_advanced_metrics(self, story: List, game_data: Dict):
        """Add advanced metrics analysis"""
        # This would implement advanced statistical analysis
        story.append(Paragraph("Advanced metrics analysis would go here", self.normal_style))
    
    def _add_key_moments(self, story: List, play_data: Dict):
        """Add key moments analysis"""
        # This would extract and analyze key moments from play-by-play data
        story.append(Paragraph("Key moments analysis would go here", self.normal_style))
    
    def _add_momentum_analysis(self, story: List, play_data: Dict):
        """Add momentum analysis"""
        # This would analyze game momentum shifts
        story.append(Paragraph("Momentum analysis would go here", self.normal_style))
    
    def _add_shot_analysis(self, story: List, play_data: Dict):
        """Add shot analysis"""
        # This would analyze shot patterns and effectiveness
        story.append(Paragraph("Shot analysis would go here", self.normal_style))
    
    def generate_enhanced_report(self, game_id: str, output_filename: str = None) -> str:
        """Generate the complete enhanced NHL post-game report"""
        print("🏒 Generating Enhanced NHL Post-Game Report 🏒")
        print("=" * 60)
        
        # Get comprehensive game data
        print("Fetching comprehensive game data...")
        game_data = self.api_client.get_comprehensive_game_data(game_id)
        
        if not game_data['game_center']:
            print("❌ Could not fetch game data")
            return None
        
        # Create output filename if not provided
        if not output_filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            away_team = game_data['game_center']['awayTeam']['abbrev']
            home_team = game_data['game_center']['homeTeam']['abbrev']
            output_filename = f"enhanced_nhl_report_{away_team}_vs_{home_team}_{timestamp}.pdf"
        
        # Create the PDF document
        doc = SimpleDocTemplate(output_filename, pagesize=letter, 
                              rightMargin=72, leftMargin=72, 
                              topMargin=72, bottomMargin=18)
        
        story = []
        
        # Add all sections
        print("Creating enhanced title page...")
        story.extend(self.create_enhanced_title_page(game_data))
        
        print("Creating enhanced score summary...")
        story.extend(self.create_enhanced_score_summary(game_data))
        
        print("Creating advanced player analytics...")
        story.extend(self.create_advanced_player_analytics(game_data))
        
        print("Creating play-by-play analysis...")
        story.extend(self.create_play_by_play_analysis(game_data))
        
        print("Creating enhanced visualizations...")
        story.extend(self.create_enhanced_visualizations(game_data))
        
        print("Creating goalie analysis...")
        story.extend(self.create_goalie_analysis(game_data))
        
        # Build the PDF
        print("Building PDF report...")
        doc.build(story)
        
        print(f"✅ Enhanced report generated successfully: {output_filename}")
        return output_filename


# Example usage
if __name__ == "__main__":
    generator = EnhancedNHLReportGenerator()
    
    # Test with a known game ID
    game_id = "2024030416"  # Example game ID
    output_file = generator.generate_enhanced_report(game_id)
    
    if output_file:
        print(f"🎉 Enhanced NHL report created: {output_file}")
    else:
        print("❌ Failed to create enhanced report")
