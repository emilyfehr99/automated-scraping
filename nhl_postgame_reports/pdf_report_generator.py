from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus.flowables import Flowable
from reportlab.lib.utils import ImageReader
from reportlab.lib.enums import TA_CENTER, TA_CENTER, TA_RIGHT
from reportlab.graphics.shapes import Drawing, String
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.charts.legends import Legend
import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd
import numpy as np
from io import BytesIO
import os
from create_header_image import create_dynamic_header

class HeaderFlowable(Flowable):
    """Custom flowable to draw header image at absolute top-left corner"""
    def __init__(self, image_path, width, height):
        self.image_path = image_path
        self.width = width
        self.height = height
        self.drawWidth = width
        self.drawHeight = height
        Flowable.__init__(self)
    
    def draw(self):
        """Draw the header image at absolute position (0,0)"""
        if os.path.exists(self.image_path):
            from reportlab.lib.utils import ImageReader
            img = ImageReader(self.image_path)
            # Draw image at absolute top-left corner (0, 0)
            self.canv.drawImage(img, 0, 0, width=self.width, height=self.height)

class PostGameReportGenerator:
    def __init__(self):
        self.styles = getSampleStyleSheet()
        self.register_fonts()
        self.setup_custom_styles()
    
    def register_fonts(self):
        """Register custom fonts with ReportLab"""
        try:
            # Register Russo One font
            pdfmetrics.registerFont(TTFont('RussoOne-Regular', '/Users/emilyfehr8/Library/Fonts/RussoOne-Regular.ttf'))
        except:
            try:
                # Fallback to system font
                pdfmetrics.registerFont(TTFont('RussoOne-Regular', '/System/Library/Fonts/Arial Bold.ttf'))
            except:
                # Use default font if all else fails
                pass
    
    def create_header_image(self, game_data):
        """Create the modern header image for the report using the user's header with team names"""
        try:
            # Use the user's header image from desktop
            header_path = "/Users/emilyfehr8/Desktop/Header.jpg"
            
            if os.path.exists(header_path):
                # Create a custom header with team names overlaid
                from PIL import Image as PILImage, ImageDraw, ImageFont
                
                # Load the header image
                header_img = PILImage.open(header_path)
                
                # Create a drawing context
                draw = ImageDraw.Draw(header_img)
                
                # Get team names with error handling
                try:
                    away_team = game_data['game_center']['awayTeam']['abbrev']
                    home_team = game_data['game_center']['homeTeam']['abbrev']
                except (KeyError, TypeError):
                    # Fallback to default team names if data is missing
                    away_team = "FLA"
                    home_team = "EDM"
                
                # Try to load Russo One font, fallback to default if not available
                try:
                    # Try to load Russo One font
                    font = ImageFont.truetype("/Users/emilyfehr8/Library/Fonts/RussoOne-Regular.ttf", 70)
                except:
                    try:
                        # Fallback to Arial Bold
                        font = ImageFont.truetype("/System/Library/Fonts/Arial Bold.ttf", 70)
                    except:
                        try:
                            font = ImageFont.truetype("Arial.ttf", 70)
                        except:
                            font = ImageFont.load_default()
                
                # Calculate team name text position (centered)
                team_text = f"{away_team} vs {home_team}"
                team_bbox = draw.textbbox((0, 0), team_text, font=font)
                team_text_width = team_bbox[2] - team_bbox[0]
                team_text_height = team_bbox[3] - team_bbox[1]
                
                team_x = (header_img.width - team_text_width) // 2
                team_y = (header_img.height - team_text_height) // 2 - 20  # Move up slightly to make room for subtitle
                
                # Draw team name white text with black outline for better visibility
                draw.text((team_x-1, team_y-1), team_text, font=font, fill=(0, 0, 0))  # Black outline
                draw.text((team_x+1, team_y-1), team_text, font=font, fill=(0, 0, 0))  # Black outline
                draw.text((team_x-1, team_y+1), team_text, font=font, fill=(0, 0, 0))  # Black outline
                draw.text((team_x+1, team_y+1), team_text, font=font, fill=(0, 0, 0))  # Black outline
                draw.text((team_x, team_y), team_text, font=font, fill=(255, 255, 255))  # White text
                
                # Create subtitle font (45pt)
                try:
                    subtitle_font = ImageFont.truetype("/Users/emilyfehr8/Library/Fonts/RussoOne-Regular.ttf", 45)
                except:
                    try:
                        subtitle_font = ImageFont.truetype("/System/Library/Fonts/Arial Bold.ttf", 45)
                    except:
                        try:
                            subtitle_font = ImageFont.truetype("Arial.ttf", 45)
                        except:
                            subtitle_font = ImageFont.load_default()
                
                # Get game date and score for subtitle
                try:
                    game_date = game_data['game_center']['game']['gameDate']
                    away_score = game_data['game_center']['game']['awayTeamScore']
                    home_score = game_data['game_center']['game']['homeTeamScore']
                    
                    # Determine winning team
                    if away_score > home_score:
                        winner = away_team
                    elif home_score > away_score:
                        winner = home_team
                    else:
                        winner = "TIE"
                        
                except (KeyError, TypeError):
                    # If we can't get real data, use sample data
                    game_date = "2024-06-15"
                    away_score = 3
                    home_score = 2
                    winner = away_team
                
                # Calculate subtitle text position (centered below team names)
                subtitle_text = f"Post Game Report: {game_date} | {away_score}-{home_score} {winner} WINS"
                subtitle_bbox = draw.textbbox((0, 0), subtitle_text, font=subtitle_font)
                subtitle_text_width = subtitle_bbox[2] - subtitle_bbox[0]
                subtitle_text_height = subtitle_bbox[3] - subtitle_bbox[1]
                
                subtitle_x = (header_img.width - subtitle_text_width) // 2
                subtitle_y = team_y + team_text_height + 85  # Position 3cm (85 points) below team names
                
                # Draw subtitle in #7F7F7F color
                draw.text((subtitle_x, subtitle_y), subtitle_text, font=subtitle_font, fill=(127, 127, 127))  # #7F7F7F
                
                # Save the modified header
                modified_header_path = "temp_header_with_teams.png"
                header_img.save(modified_header_path)
                
                # Create ReportLab Image object
                header_image = Image(modified_header_path, width=612, height=150)
                header_image.hAlign = 'CENTER'
                header_image.vAlign = 'TOP'
                
                # Store the temp file path for cleanup
                header_image.temp_path = modified_header_path
                
                return header_image
            else:
                print(f"Warning: Header image not found at {header_path}")
                return None
                
        except Exception as e:
            print(f"Warning: Could not create header image: {e}")
            return None
    
    def setup_custom_styles(self):
        """Setup custom paragraph styles for the report"""
        # Title style
        self.title_style = ParagraphStyle(
            'CustomTitle',
            parent=self.styles['Heading1'],
            fontSize=24,
            textColor=colors.darkblue,
            alignment=TA_CENTER,
            spaceAfter=20,
            fontName='RussoOne-Regular'
        )
        
        # Subtitle style
        self.subtitle_style = ParagraphStyle(
            'CustomSubtitle',
            parent=self.styles['Heading2'],
            fontSize=18,
            textColor=colors.darkblue,
            alignment=TA_CENTER,
            spaceAfter=15,
            fontName='RussoOne-Regular'
        )
        
        # Section header style
        self.section_style = ParagraphStyle(
            'CustomSection',
            parent=self.styles['Heading3'],
            fontSize=14,
            textColor=colors.darkred,
            alignment=TA_CENTER,
            spaceAfter=10,
            fontName='RussoOne-Regular'
        )
        
        # Normal text style
        self.normal_style = ParagraphStyle(
            'CustomNormal',
            parent=self.styles['Normal'],
            fontSize=10,
            textColor=colors.black,
            alignment=TA_CENTER,
            spaceAfter=6,
            fontName='RussoOne-Regular'
        )
        
        # Stat text style
        self.stat_style = ParagraphStyle(
            'CustomStat',
            parent=self.styles['Normal'],
            fontSize=11,
            textColor=colors.darkgreen,
            alignment=TA_CENTER,
            spaceAfter=4,
            fontName='RussoOne-Regular'
        )
    
    def create_score_summary(self, game_data):
        """Create the score summary section"""
        story = []
        
        # Game header
        game_info = game_data['game_center']['game']
        away_team = game_data['game_center']['awayTeam']
        home_team = game_data['game_center']['homeTeam']
        
        story.append(Paragraph(f"FINAL SCORE", self.title_style))
        story.append(Spacer(1, 20))
        
        # Score display
        score_data = [
            ['', '1st', '2nd', '3rd', 'OT', 'Total'],
            [away_team['abbrev'], 
             game_info['awayTeamScoreByPeriod'][0] if len(game_info['awayTeamScoreByPeriod']) > 0 else 0,
             game_info['awayTeamScoreByPeriod'][1] if len(game_info['awayTeamScoreByPeriod']) > 1 else 0,
             game_info['awayTeamScoreByPeriod'][2] if len(game_info['awayTeamScoreByPeriod']) > 2 else 0,
             game_info['awayTeamScoreByPeriod'][3] if len(game_info['awayTeamScoreByPeriod']) > 3 else 0,
             game_info['awayTeamScore']],
            [home_team['abbrev'],
             game_info['homeTeamScoreByPeriod'][0] if len(game_info['homeTeamScoreByPeriod']) > 0 else 0,
             game_info['homeTeamScoreByPeriod'][1] if len(game_info['homeTeamScoreByPeriod']) > 1 else 0,
             game_info['homeTeamScoreByPeriod'][2] if len(game_info['homeTeamScoreByPeriod']) > 2 else 0,
             game_info['homeTeamScoreByPeriod'][3] if len(game_info['homeTeamScoreByPeriod']) > 3 else 0,
             game_info['homeTeamScore']]
        ]
        
        score_table = Table(score_data, colWidths=[1.5*inch, 0.8*inch, 0.8*inch, 0.8*inch, 0.8*inch, 1*inch])
        score_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.darkblue),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'RussoOne-Regular'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('FONTNAME', (0, 1), (-1, -1), 'RussoOne-Regular'),
        ]))
        
        story.append(score_table)
        story.append(Spacer(1, 20))
        
        return story
    
    def _create_player_roster_map(self, play_by_play):
        """Create a mapping of player IDs to player info"""
        roster_map = {}
        if 'rosterSpots' in play_by_play:
            for player in play_by_play['rosterSpots']:
                player_id = player['playerId']
                roster_map[player_id] = {
                    'firstName': player['firstName']['default'],
                    'lastName': player['lastName']['default'],
                    'sweaterNumber': player['sweaterNumber'],
                    'positionCode': player['positionCode'],
                    'teamId': player['teamId']
                }
        return roster_map

    def _calculate_team_stats_from_play_by_play(self, game_data, team_side):
        """Calculate team statistics from play-by-play data"""
        try:
            play_by_play = game_data.get('play_by_play')
            if not play_by_play or 'plays' not in play_by_play:
                return self._calculate_team_stats_from_players(game_data['boxscore'], team_side)
            
            # Get team ID for filtering
            boxscore = game_data['boxscore']
            team_id = boxscore[team_side]['id']
            
            # Create player roster map
            roster_map = self._create_player_roster_map(play_by_play)
            
            # Initialize counters
            stats = {
                'hits': 0,
                'penaltyMinutes': 0,
                'blockedShots': 0,
                'giveaways': 0,
                'takeaways': 0,
                'powerPlayGoals': 0,
                'powerPlayOpportunities': 0,
                'faceoffWins': 0,
                'faceoffTotal': 0
            }
            
            # Process each play
            for play in play_by_play['plays']:
                play_details = play.get('details', {})
                event_owner_team_id = play_details.get('eventOwnerTeamId')
                play_type = play.get('typeDescKey', '')
                
                # Only count plays for this team
                if event_owner_team_id == team_id:
                    if play_type == 'hit':
                        stats['hits'] += 1
                    elif play_type == 'blocked-shot':
                        stats['blockedShots'] += 1
                    elif play_type == 'giveaway':
                        stats['giveaways'] += 1
                    elif play_type == 'takeaway':
                        stats['takeaways'] += 1
                    elif play_type == 'faceoff':
                        stats['faceoffTotal'] += 1
                        # Check if this team won the faceoff
                        winning_player_id = play_details.get('winningPlayerId')
                        if winning_player_id and winning_player_id in roster_map:
                            if roster_map[winning_player_id]['teamId'] == team_id:
                                stats['faceoffWins'] += 1
                    elif play_type == 'penalty':
                        duration = play_details.get('duration', 0)
                        stats['penaltyMinutes'] += duration
                    elif play_type == 'goal':
                        # Check if it's a power play goal
                        situation_code = play.get('situationCode', '')
                        if situation_code.startswith('14'):  # Power play situation
                            stats['powerPlayGoals'] += 1
                
                # Count power play opportunities (penalties against the other team)
                elif event_owner_team_id != team_id and play_type == 'penalty':
                    situation_code = play.get('situationCode', '')
                    if situation_code.startswith('14'):  # Power play situation
                        stats['powerPlayOpportunities'] += 1
            
            return stats
            
        except (KeyError, TypeError) as e:
            print(f"Error calculating stats from play-by-play: {e}")
            # Fallback to player stats
            return self._calculate_team_stats_from_players(game_data['boxscore'], team_side)
    
    def _calculate_player_stats_from_play_by_play(self, game_data, team_side):
        """Calculate individual player statistics from play-by-play data"""
        try:
            play_by_play = game_data.get('play_by_play')
            if not play_by_play or 'plays' not in play_by_play:
                return {}
            
            # Get team ID for filtering
            boxscore = game_data['boxscore']
            team_id = boxscore[team_side]['id']
            
            # Create player roster map
            roster_map = self._create_player_roster_map(play_by_play)
            
            # Initialize player stats
            player_stats = {}
            for player_id, player_info in roster_map.items():
                if player_info['teamId'] == team_id:
                    player_stats[player_id] = {
                        'name': f"{player_info['firstName']} {player_info['lastName']}",
                        'position': player_info['positionCode'],
                        'sweaterNumber': player_info['sweaterNumber'],
                        'goals': 0,
                        'assists': 0,
                        'points': 0,
                        'plusMinus': 0,
                        'pim': 0,
                        'sog': 0,
                        'hits': 0,
                        'blockedShots': 0,
                        'giveaways': 0,
                        'takeaways': 0,
                        'faceoffWins': 0,
                        'faceoffTotal': 0
                    }
            
            # Process each play
            for play in play_by_play['plays']:
                play_details = play.get('details', {})
                event_owner_team_id = play_details.get('eventOwnerTeamId')
                play_type = play.get('typeDescKey', '')
                
                # Only process plays for this team
                if event_owner_team_id == team_id:
                    # Get the primary player involved
                    primary_player_id = None
                    if play_type == 'goal':
                        primary_player_id = play_details.get('scoringPlayerId')
                        assist1_player_id = play_details.get('assist1PlayerId')
                        assist2_player_id = play_details.get('assist2PlayerId')
                        
                        # Count goal
                        if primary_player_id and primary_player_id in player_stats:
                            player_stats[primary_player_id]['goals'] += 1
                            player_stats[primary_player_id]['points'] += 1
                        
                        # Count assists
                        if assist1_player_id and assist1_player_id in player_stats:
                            player_stats[assist1_player_id]['assists'] += 1
                            player_stats[assist1_player_id]['points'] += 1
                        if assist2_player_id and assist2_player_id in player_stats:
                            player_stats[assist2_player_id]['assists'] += 1
                            player_stats[assist2_player_id]['points'] += 1
                    
                    elif play_type == 'shot-on-goal':
                        primary_player_id = play_details.get('shootingPlayerId')
                        if primary_player_id and primary_player_id in player_stats:
                            player_stats[primary_player_id]['sog'] += 1
                    
                    elif play_type == 'hit':
                        primary_player_id = play_details.get('hittingPlayerId')
                        if primary_player_id and primary_player_id in player_stats:
                            player_stats[primary_player_id]['hits'] += 1
                    
                    elif play_type == 'blocked-shot':
                        primary_player_id = play_details.get('blockingPlayerId')
                        if primary_player_id and primary_player_id in player_stats:
                            player_stats[primary_player_id]['blockedShots'] += 1
                    
                    elif play_type == 'giveaway':
                        primary_player_id = play_details.get('playerId')
                        if primary_player_id and primary_player_id in player_stats:
                            player_stats[primary_player_id]['giveaways'] += 1
                    
                    elif play_type == 'takeaway':
                        primary_player_id = play_details.get('playerId')
                        if primary_player_id and primary_player_id in player_stats:
                            player_stats[primary_player_id]['takeaways'] += 1
                    
                    elif play_type == 'faceoff':
                        winning_player_id = play_details.get('winningPlayerId')
                        losing_player_id = play_details.get('losingPlayerId')
                        
                        if winning_player_id and winning_player_id in player_stats:
                            player_stats[winning_player_id]['faceoffWins'] += 1
                            player_stats[winning_player_id]['faceoffTotal'] += 1
                        if losing_player_id and losing_player_id in player_stats:
                            player_stats[losing_player_id]['faceoffTotal'] += 1
                    
                    elif play_type == 'penalty':
                        primary_player_id = play_details.get('committedByPlayerId')
                        duration = play_details.get('duration', 0)
                        if primary_player_id and primary_player_id in player_stats:
                            player_stats[primary_player_id]['pim'] += duration
            
            return player_stats
            
        except (KeyError, TypeError) as e:
            print(f"Error calculating player stats from play-by-play: {e}")
            return {}
    
    def _calculate_team_stats_from_players(self, boxscore, team_side):
        """Calculate team statistics from individual player data (fallback)"""
        try:
            player_stats = boxscore['playerByGameStats'][team_side]
            
            # Initialize counters
            stats = {
                'hits': 0,
                'penaltyMinutes': 0,
                'blockedShots': 0,
                'giveaways': 0,
                'takeaways': 0,
                'powerPlayGoals': 0,
                'powerPlayOpportunities': 0,
                'faceoffWins': 0,
                'faceoffTotal': 0
            }
            
            # Sum up stats from all players (forwards, defense, goalies)
            for position_group in ['forwards', 'defense', 'goalies']:
                if position_group in player_stats:
                    for player in player_stats[position_group]:
                        stats['hits'] += player.get('hits', 0)
                        stats['penaltyMinutes'] += player.get('pim', 0)
                        stats['blockedShots'] += player.get('blockedShots', 0)
                        stats['giveaways'] += player.get('giveaways', 0)
                        stats['takeaways'] += player.get('takeaways', 0)
                        stats['powerPlayGoals'] += player.get('powerPlayGoals', 0)
                        
                        # Faceoff calculations (only for forwards)
                        if position_group == 'forwards':
                            faceoff_pct = player.get('faceoffWinningPctg', 0)
                            if faceoff_pct > 0:  # Only count if player took faceoffs
                                # Estimate total faceoffs from percentage (this is approximate)
                                estimated_faceoffs = 10  # Rough estimate
                                wins = int(faceoff_pct * estimated_faceoffs)
                                stats['faceoffWins'] += wins
                                stats['faceoffTotal'] += estimated_faceoffs
            
            return stats
            
        except (KeyError, TypeError):
            # Return default values if data is missing
            return {
                'hits': 0,
                'penaltyMinutes': 0,
                'blockedShots': 0,
                'giveaways': 0,
                'takeaways': 0,
                'powerPlayGoals': 0,
                'powerPlayOpportunities': 0,
                'faceoffWins': 0,
                'faceoffTotal': 0
            }
    
    def create_team_stats_comparison(self, game_data):
        """Create team statistics comparison section"""
        story = []
        
        story.append(Paragraph("TEAM STATISTICS COMPARISON", self.subtitle_style))
        story.append(Spacer(1, 15))
        
        # Get team stats from boxscore
        boxscore = game_data['boxscore']
        away_stats = boxscore['awayTeam']
        home_stats = boxscore['homeTeam']
        
        # Calculate team statistics from play-by-play data (more accurate)
        away_team_stats = self._calculate_team_stats_from_play_by_play(game_data, 'awayTeam')
        home_team_stats = self._calculate_team_stats_from_play_by_play(game_data, 'homeTeam')
        
        # Create stats comparison table
        stats_data = [
            ['Statistic', away_stats['abbrev'], home_stats['abbrev']],
            ['Goals', away_stats['score'], home_stats['score']],
            ['Shots', away_stats.get('sog', 'N/A'), home_stats.get('sog', 'N/A')],
            ['Power Play', f"{away_team_stats['powerPlayGoals']}/{away_team_stats['powerPlayOpportunities']}", f"{home_team_stats['powerPlayGoals']}/{home_team_stats['powerPlayOpportunities']}"],
            ['Penalty Minutes', away_team_stats['penaltyMinutes'], home_team_stats['penaltyMinutes']],
            ['Hits', away_team_stats['hits'], home_team_stats['hits']],
            ['Faceoff Wins', f"{away_team_stats['faceoffWins']}/{away_team_stats['faceoffTotal']}", f"{home_team_stats['faceoffWins']}/{home_team_stats['faceoffTotal']}"],
            ['Blocked Shots', away_team_stats['blockedShots'], home_team_stats['blockedShots']],
            ['Giveaways', away_team_stats['giveaways'], home_team_stats['giveaways']],
            ['Takeaways', away_team_stats['takeaways'], home_team_stats['takeaways']]
        ]
        
        stats_table = Table(stats_data, colWidths=[2*inch, 1.5*inch, 1.5*inch])
        stats_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.darkred),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'RussoOne-Regular'),
            ('FONTSIZE', (0, 0), (-1, 0), 11),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
            ('BACKGROUND', (0, 1), (-1, -1), colors.lightgrey),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('FONTNAME', (0, 1), (-1, -1), 'RussoOne-Regular'),
        ]))
        
        story.append(stats_table)
        story.append(Spacer(1, 20))
        
        return story
    
    def create_scoring_summary(self, game_data):
        """Create scoring summary section"""
        story = []
        
        story.append(Paragraph("SCORING SUMMARY", self.subtitle_style))
        story.append(Spacer(1, 15))
        
        # Get scoring plays
        plays = game_data['game_center'].get('plays', [])
        scoring_plays = [play for play in plays if play.get('typeDescKey') == 'goal']
        
        if scoring_plays:
            # Create scoring summary table
            scoring_data = [['Period', 'Time', 'Team', 'Scorer', 'Assists', 'Score']]
            
            for play in scoring_plays:
                period = play.get('periodNumber', 'N/A')
                time = play.get('timeInPeriod', 'N/A')
                team = play.get('team', {}).get('abbrev', 'N/A')
                scorer = play.get('scorer', {}).get('name', 'N/A')
                
                # Get assists
                assists = []
                for player in play.get('players', []):
                    if player.get('playerType') == 'assist':
                        assists.append(player.get('name', 'N/A'))
                
                assists_str = ', '.join(assists) if assists else 'Unassisted'
                
                # Get score at time of goal
                score = play.get('score', 'N/A')
                
                scoring_data.append([period, time, team, scorer, assists_str, score])
            
            scoring_table = Table(scoring_data, colWidths=[0.8*inch, 1*inch, 1.2*inch, 2*inch, 2.5*inch, 1*inch])
            scoring_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.darkgreen),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'RussoOne-Regular'),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
                ('BACKGROUND', (0, 1), (-1, -1), colors.lightgreen),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('FONTSIZE', (0, 1), (-1, -1), 8),
                ('FONTNAME', (0, 1), (-1, -1), 'RussoOne-Regular'),
                ('ALIGN', (3, 1), (4, -1), 'CENTER'),  # Left align scorer and assists columns
            ]))
            
            story.append(scoring_table)
        else:
            story.append(Paragraph("No scoring information available", self.normal_style))
        
        story.append(Spacer(1, 20))
        return story
    
    def create_player_performance(self, game_data):
        """Create comprehensive player performance section using play-by-play data"""
        story = []
        
        story.append(Paragraph("PLAYER PERFORMANCE", self.subtitle_style))
        story.append(Spacer(1, 15))
        
        boxscore = game_data['boxscore']
        
        # Away team players
        away_team = boxscore['awayTeam']
        story.append(Paragraph(f"<b>{away_team['abbrev']} Players</b>", self.normal_style))
        
        # Get player stats from play-by-play data
        away_player_stats = self._calculate_player_stats_from_play_by_play(game_data, 'awayTeam')
        
        away_players = []
        if away_player_stats:
            # Sort by points, then goals, then assists
            sorted_players = sorted(away_player_stats.values(), 
                                  key=lambda x: (x['points'], x['goals'], x['assists']), 
                                  reverse=True)
            
            for player in sorted_players:
                away_players.append([
                    f"#{player['sweaterNumber']} {player['name']}",
                    player['position'],
                    player['goals'],
                    player['assists'],
                    player['points'],
                    player['plusMinus'],
                    player['pim'],
                    player['sog'],
                    player['hits'],
                    player['blockedShots']
                ])
        else:
            # Fallback to boxscore data
            for position_group in ['forwards', 'defense', 'goalies']:
                if position_group in boxscore['playerByGameStats']['awayTeam']:
                    for player in boxscore['playerByGameStats']['awayTeam'][position_group]:
                        away_players.append([
                            player.get('name', 'Unknown'),
                            player.get('position', 'N/A'),
                            player.get('goals', 0),
                            player.get('assists', 0),
                            player.get('points', 0),
                            player.get('plusMinus', 0),
                            player.get('pim', 0),
                            player.get('sog', 0),
                            player.get('hits', 0),
                            player.get('blockedShots', 0)
                        ])
        
        if away_players:
            away_table = Table(away_players, colWidths=[1.8*inch, 0.4*inch, 0.3*inch, 0.3*inch, 0.3*inch, 0.3*inch, 0.3*inch, 0.3*inch, 0.3*inch, 0.3*inch])
            away_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.darkred),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'RussoOne-Regular'),
                ('FONTSIZE', (0, 0), (-1, 0), 8),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
                ('BACKGROUND', (0, 1), (-1, -1), colors.lightgrey),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('FONTSIZE', (0, 1), (-1, -1), 7),
                ('FONTNAME', (0, 1), (-1, -1), 'RussoOne-Regular'),
            ]))
            story.append(away_table)
        
        story.append(Spacer(1, 20))
        
        # Home team players
        home_team = boxscore['homeTeam']
        story.append(Paragraph(f"<b>{home_team['abbrev']} Players</b>", self.normal_style))
        
        # Get player stats from play-by-play data
        home_player_stats = self._calculate_player_stats_from_play_by_play(game_data, 'homeTeam')
        
        home_players = []
        if home_player_stats:
            # Sort by points, then goals, then assists
            sorted_players = sorted(home_player_stats.values(), 
                                  key=lambda x: (x['points'], x['goals'], x['assists']), 
                                  reverse=True)
            
            for player in sorted_players:
                home_players.append([
                    f"#{player['sweaterNumber']} {player['name']}",
                    player['position'],
                    player['goals'],
                    player['assists'],
                    player['points'],
                    player['plusMinus'],
                    player['pim'],
                    player['sog'],
                    player['hits'],
                    player['blockedShots']
                ])
        else:
            # Fallback to boxscore data
            for position_group in ['forwards', 'defense', 'goalies']:
                if position_group in boxscore['playerByGameStats']['homeTeam']:
                    for player in boxscore['playerByGameStats']['homeTeam'][position_group]:
                        home_players.append([
                            player.get('name', 'Unknown'),
                            player.get('position', 'N/A'),
                            player.get('goals', 0),
                            player.get('assists', 0),
                            player.get('points', 0),
                            player.get('plusMinus', 0),
                            player.get('pim', 0),
                            player.get('sog', 0),
                            player.get('hits', 0),
                            player.get('blockedShots', 0)
                        ])
        
        if home_players:
            home_table = Table(home_players, colWidths=[1.8*inch, 0.4*inch, 0.3*inch, 0.3*inch, 0.3*inch, 0.3*inch, 0.3*inch, 0.3*inch, 0.3*inch, 0.3*inch])
            home_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.darkred),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'RussoOne-Regular'),
                ('FONTSIZE', (0, 0), (-1, 0), 8),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
                ('BACKGROUND', (0, 1), (-1, -1), colors.lightgrey),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('FONTSIZE', (0, 1), (-1, -1), 7),
                ('FONTNAME', (0, 1), (-1, -1), 'RussoOne-Regular'),
            ]))
            story.append(home_table)
        
        story.append(Spacer(1, 20))
        return story
    
    def create_goalie_performance(self, game_data):
        """Create goalie performance section"""
        story = []
        
        story.append(Paragraph("GOALIE PERFORMANCE", self.subtitle_style))
        story.append(Spacer(1, 15))
        
        # Get goalie stats from boxscore
        boxscore = game_data['boxscore']
        away_goalies = []
        home_goalies = []
        
        # Find goalies in player lists
        for player in boxscore.get('awayTeam', {}).get('players', []):
            if player.get('position', '').upper() == 'G':
                away_goalies.append(player)
        
        for player in boxscore.get('homeTeam', {}).get('players', []):
            if player.get('position', '').upper() == 'G':
                home_goalies.append(player)
        
        # Create goalie comparison table
        goalie_data = [['Team', 'Goalie', 'Shots Against', 'Saves', 'Save %', 'Goals Against', 'Time on Ice']]
        
        for goalie in away_goalies:
            stats = goalie.get('stats', {})
            shots_against = stats.get('shotsAgainst', 0)
            saves = stats.get('saves', 0)
            goals_against = stats.get('goalsAgainst', 0)
            save_pct = f"{(saves/shots_against*100):.1f}%" if shots_against > 0 else "N/A"
            time_on_ice = stats.get('timeOnIce', 'N/A')
            
            goalie_data.append([
                boxscore['awayTeam']['abbrev'],
                goalie.get('name', 'Unknown'),
                shots_against,
                saves,
                save_pct,
                goals_against,
                time_on_ice
            ])
        
        for goalie in home_goalies:
            stats = goalie.get('stats', {})
            shots_against = stats.get('shotsAgainst', 0)
            saves = stats.get('saves', 0)
            goals_against = stats.get('goalsAgainst', 0)
            save_pct = f"{(saves/shots_against*100):.1f}%" if shots_against > 0 else "N/A"
            time_on_ice = stats.get('timeOnIce', 'N/A')
            
            goalie_data.append([
                boxscore['homeTeam']['abbrev'],
                goalie.get('name', 'Unknown'),
                shots_against,
                saves,
                save_pct,
                goals_against,
                time_on_ice
            ])
        
        if len(goalie_data) > 1:  # If we have goalie data
            goalie_table = Table(goalie_data, colWidths=[1.2*inch, 2*inch, 1*inch, 0.8*inch, 1*inch, 1*inch, 1.2*inch])
            goalie_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.darkblue),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'RussoOne-Regular'),
                ('FONTSIZE', (0, 0), (-1, 0), 9),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
                ('BACKGROUND', (0, 1), (-1, -1), colors.lightblue),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('FONTSIZE', (0, 1), (-1, -1), 8),
                ('FONTNAME', (0, 1), (-1, -1), 'RussoOne-Regular'),
            ]))
            story.append(goalie_table)
        else:
            story.append(Paragraph("No goalie performance data available", self.normal_style))
        
        story.append(Spacer(1, 20))
        return story
    
    def create_game_analysis(self, game_data):
        """Create game analysis and key moments section"""
        story = []
        
        story.append(Paragraph("GAME ANALYSIS & KEY MOMENTS", self.subtitle_style))
        story.append(Spacer(1, 15))
        
        # Analyze the game flow
        game_info = game_data['game_center']['game']
        away_team = game_data['game_center']['awayTeam']
        home_team = game_data['game_center']['homeTeam']
        
        # Determine winner and margin
        away_score = game_info['awayTeamScore']
        home_score = game_info['homeTeamScore']
        
        if away_score > home_score:
            winner = away_team['abbrev']
            loser = home_team['abbrev']
            margin = away_score - home_score
        else:
            winner = home_team['abbrev']
            loser = away_team['abbrev']
            margin = home_score - away_score
        
        # Game summary
        story.append(Paragraph(f"<b>Game Summary:</b>", self.section_style))
        story.append(Paragraph(f"The {winner} defeated the {loser} by a score of {max(away_score, home_score)}-{min(away_score, home_score)}.", self.normal_style))
        
        if margin == 1:
            story.append(Paragraph("This was a close, competitive game that could have gone either way.", self.normal_style))
        elif margin <= 3:
            story.append(Paragraph("The game was competitive with a moderate margin of victory.", self.normal_style))
        else:
            story.append(Paragraph("This was a decisive victory with a significant margin.", self.normal_style))
        
        story.append(Spacer(1, 10))
        
        # Key moments analysis
        story.append(Paragraph(f"<b>Key Moments:</b>", self.section_style))
        
        # Analyze scoring by period
        away_periods = game_info.get('awayTeamScoreByPeriod', [])
        home_periods = game_info.get('homeTeamScoreByPeriod', [])
        
        if len(away_periods) >= 3:
            story.append(Paragraph(f"• First Period: {away_team['abbrev']} {away_periods[0]} - {home_team['abbrev']} {home_periods[0]}", self.normal_style))
            story.append(Paragraph(f"• Second Period: {away_team['abbrev']} {away_periods[1]} - {home_team['abbrev']} {home_periods[1]}", self.normal_style))
            story.append(Paragraph(f"• Third Period: {away_team['abbrev']} {away_periods[2]} - {home_team['abbrev']} {home_periods[2]}", self.normal_style))
            
            if len(away_periods) > 3:
                story.append(Paragraph(f"• Overtime: {away_team['abbrev']} {away_periods[3]} - {home_team['abbrev']} {home_periods[3]}", self.normal_style))
        
        story.append(Spacer(1, 10))
        
        # Special teams analysis
        story.append(Paragraph(f"<b>Special Teams:</b>", self.section_style))
        
        # Get power play and penalty kill info from boxscore
        boxscore = game_data['boxscore']
        away_pp = boxscore.get('awayTeam', {}).get('powerPlayConversion', 'N/A')
        home_pp = boxscore.get('homeTeam', {}).get('powerPlayConversion', 'N/A')
        
        story.append(Paragraph(f"• {away_team['abbrev']} Power Play: {away_pp}", self.normal_style))
        story.append(Paragraph(f"• {home_team['abbrev']} Power Play: {home_pp}", self.normal_style))
        
        story.append(Spacer(1, 20))
        return story
    
    def create_visualizations(self, game_data):
        """Create charts and visualizations"""
        story = []
        
        story.append(Paragraph("GAME VISUALIZATIONS", self.subtitle_style))
        story.append(Spacer(1, 15))
        
        # Create shot comparison chart
        try:
            boxscore = game_data['boxscore']
            away_team = boxscore['awayTeam']['abbrev']
            home_team = boxscore['homeTeam']['abbrev']
            
            # Get shots on goal
            away_shots = boxscore['awayTeam'].get('sog', 0)
            home_shots = boxscore['homeTeam'].get('sog', 0)
            
            # Create matplotlib chart
            fig, ax = plt.subplots(figsize=(8, 6))
            teams = [away_team, home_team]
            shots = [away_shots, home_shots]
            colors_chart = ['#C8102E', '#FF6B35']  # Red and Orange
            
            bars = ax.bar(teams, shots, color=colors_chart, alpha=0.8)
            ax.set_title('Shots on Goal Comparison', fontsize=16, fontweight='bold')
            ax.set_ylabel('Shots on Goal', fontsize=12)
            ax.set_xlabel('Team', fontsize=12)
            
            # Add value labels on bars
            for bar, shot in zip(bars, shots):
                height = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2., height + 0.5,
                       f'{shot}', ha='center', va='bottom', fontweight='bold')
            
            plt.tight_layout()
            
            # Save to BytesIO and convert to ReportLab Image
            img_buffer = BytesIO()
            plt.savefig(img_buffer, format='png', dpi=300, bbox_inches='tight')
            img_buffer.seek(0)
            
            # Create ReportLab Image
            img = Image(img_buffer)
            img.drawHeight = 4*inch
            img.drawWidth = 6*inch
            
            story.append(img)
            story.append(Spacer(1, 15))
            
            plt.close()
            
        except Exception as e:
            story.append(Paragraph(f"Chart generation error: {str(e)}", self.normal_style))
        
        # Create scoring by period chart
        try:
            game_info = game_data['game_center']['game']
            away_periods = game_info.get('awayTeamScoreByPeriod', [0, 0, 0])
            home_periods = game_info.get('homeTeamScoreByPeriod', [0, 0, 0])
            
            # Ensure we have at least 3 periods
            while len(away_periods) < 3:
                away_periods.append(0)
            while len(home_periods) < 3:
                home_periods.append(0)
            
            periods = ['1st', '2nd', '3rd']
            if len(away_periods) > 3:
                periods.append('OT')
            
            fig, ax = plt.subplots(figsize=(8, 6))
            x = np.arange(len(periods))
            width = 0.35
            
            bars1 = ax.bar(x - width/2, away_periods[:len(periods)], width, 
                          label=away_team, color='#C8102E', alpha=0.8)
            bars2 = ax.bar(x + width/2, home_periods[:len(periods)], width, 
                          label=home_team, color='#FF6B35', alpha=0.8)
            
            ax.set_title('Scoring by Period', fontsize=16, fontweight='bold')
            ax.set_ylabel('Goals', fontsize=12)
            ax.set_xlabel('Period', fontsize=12)
            ax.set_xticks(x)
            ax.set_xticklabels(periods)
            ax.legend()
            
            # Add value labels on bars
            for bars in [bars1, bars2]:
                for bar in bars:
                    height = bar.get_height()
                    if height > 0:
                        ax.text(bar.get_x() + bar.get_width()/2., height + 0.05,
                               f'{int(height)}', ha='center', va='bottom', fontweight='bold')
            
            plt.tight_layout()
            
            # Save to BytesIO and convert to ReportLab Image
            img_buffer = BytesIO()
            plt.savefig(img_buffer, format='png', dpi=300, bbox_inches='tight')
            img_buffer.seek(0)
            
            # Create ReportLab Image
            img = Image(img_buffer)
            img.drawHeight = 4*inch
            img.drawWidth = 6*inch
            
            story.append(img)
            
            plt.close()
            
        except Exception as e:
            story.append(Paragraph(f"Period scoring chart error: {str(e)}", self.normal_style))
        
        story.append(Spacer(1, 20))
        return story
    
    def generate_report(self, game_data, output_filename):
        """Generate the complete post-game report PDF"""
        # Set margins to allow header to extend to edges
        doc = SimpleDocTemplate(output_filename, pagesize=letter, rightMargin=72, leftMargin=72, 
                              topMargin=0, bottomMargin=18)
        
        story = []
        
        # Add modern header image at the absolute top of the page (height 0)
        header_image = self.create_header_image(game_data)
        if header_image:
            print(f"Header image loaded: {header_image.drawWidth}x{header_image.drawHeight}")
            # Header starts at exact top of page (0 points from top)
            # Covers full 8.5 inches width (612 points)
            # Use negative spacer to pull header to absolute top
            story.append(Spacer(1, -20))  # Negative spacer to pull up
            story.append(header_image)
            story.append(Spacer(1, 20))  # Minimal space after header
        else:
            print("Warning: Header image failed to load")
        
        # Add left margin for content (since header uses negative margin)
        
        
        # Add content with proper margins (since we removed page margins for header)
        story.append(Spacer(1, 0))  # No top spacing
        
        # Add all sections
        story.extend(self.create_score_summary(game_data))
        story.extend(self.create_team_stats_comparison(game_data))
        story.extend(self.create_scoring_summary(game_data))
        story.extend(self.create_player_performance(game_data))
        story.extend(self.create_goalie_performance(game_data))
        story.extend(self.create_game_analysis(game_data))
        story.extend(self.create_visualizations(game_data))
        
        # Build the PDF
        doc.build(story)
        
        # Clean up temporary header file if it exists
        if header_image and hasattr(header_image, 'temp_path'):
            try:
                os.remove(header_image.temp_path)
                print(f"Cleaned up temporary header file: {header_image.temp_path}")
            except:
                pass
        
        print(f"Post-game report generated successfully: {output_filename}")
