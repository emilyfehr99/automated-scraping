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
from advanced_metrics_analyzer import AdvancedMetricsAnalyzer
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
                
                # Load team logos
                away_logo = None
                home_logo = None
                
                try:
                    import requests
                    from io import BytesIO
                    
                    # Get team abbreviations from boxscore data
                    away_team_abbrev = game_data['boxscore']['awayTeam']['abbrev']
                    home_team_abbrev = game_data['boxscore']['homeTeam']['abbrev']
                    
                    # Try to load team logos from ESPN API using team abbreviations
                    away_logo_url = f"https://a.espncdn.com/i/teamlogos/nhl/500/{away_team_abbrev.lower()}.png"
                    home_logo_url = f"https://a.espncdn.com/i/teamlogos/nhl/500/{home_team_abbrev.lower()}.png"
                    
                    # Download away team logo
                    away_response = requests.get(away_logo_url, timeout=5)
                    if away_response.status_code == 200:
                        away_logo = PILImage.open(BytesIO(away_response.content))
                        away_logo = away_logo.resize((240, 212), PILImage.Resampling.LANCZOS)
                        print(f"Loaded away team logo: {away_team}")
                    
                    # Download home team logo
                    home_response = requests.get(home_logo_url, timeout=5)
                    if home_response.status_code == 200:
                        home_logo = PILImage.open(BytesIO(home_response.content))
                        home_logo = home_logo.resize((240, 212), PILImage.Resampling.LANCZOS)
                        print(f"Loaded home team logo: {home_team}")
                        
                except Exception as e:
                    print(f"Could not load team logos: {e}")
                
                # Draw team logos if available
                if away_logo:
                    # Position away logo to the left of team text (moved 5cm left, condensed height)
                    away_logo_x = team_x - 270  # Moved 5cm (140px) further left
                    away_logo_y = team_y - 106  # Centered vertically for condensed height
                    header_img.paste(away_logo, (away_logo_x, away_logo_y), away_logo)
                
                if home_logo:
                    # Position home logo to the right of team text (condensed height)
                    home_logo_x = team_x + team_text_width + 10  # Right to accommodate 2x logo
                    home_logo_y = team_y - 106  # Centered vertically for condensed height
                    header_img.paste(home_logo, (home_logo_x, home_logo_y), home_logo)
                
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
        
        # Get team info
        boxscore = game_data['boxscore']
        away_team = boxscore['awayTeam']
        home_team = boxscore['homeTeam']
        
        story.append(Paragraph(f"FINAL SCORE", self.title_style))
        story.append(Spacer(1, 20))
        
        # Calculate period scores from play-by-play data
        away_period_scores = [0, 0, 0, 0]  # 1st, 2nd, 3rd, OT
        home_period_scores = [0, 0, 0, 0]  # 1st, 2nd, 3rd, OT
        
        play_by_play = game_data.get('play_by_play')
        if play_by_play and 'plays' in play_by_play:
            for play in play_by_play['plays']:
                if play.get('typeDescKey') == 'goal':
                    details = play.get('details', {})
                    period = play.get('periodDescriptor', {}).get('number', 1)
                    event_team = details.get('eventOwnerTeamId')
                    
                    # Adjust period index (period 1 = index 0, etc.)
                    period_index = min(period - 1, 3)  # Cap at OT (index 3)
                    
                    if event_team == away_team['id']:
                        away_period_scores[period_index] += 1
                    elif event_team == home_team['id']:
                        home_period_scores[period_index] += 1
        
        # Calculate totals
        away_total = sum(away_period_scores)
        home_total = sum(home_period_scores)
        
        # Score display
        score_data = [
            ['', '1st', '2nd', '3rd', 'OT', 'Total'],
            [away_team['abbrev'], 
             away_period_scores[0],
             away_period_scores[1], 
             away_period_scores[2],
             away_period_scores[3],
             away_total],
            [home_team['abbrev'],
             home_period_scores[0],
             home_period_scores[1],
             home_period_scores[2], 
             home_period_scores[3],
             home_total]
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
                'faceoffTotal': 0,
                'shotsOnGoal': 0,
                'missedShots': 0
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
                    elif play_type == 'shot-on-goal':
                        stats['shotsOnGoal'] += 1
                    elif play_type == 'missed-shot':
                        stats['missedShots'] += 1
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
                        'faceoffTotal': 0,
                        'primaryAssists': 0,
                        'secondaryAssists': 0,
                        'penaltiesDrawn': 0,
                        'penaltiesTaken': 0,
                        'goalsFor': 0,
                        'goalsAgainst': 0,
                        'gameScore': 0.0
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
                        
                        # Count assists (primary and secondary)
                        if assist1_player_id and assist1_player_id in player_stats:
                            player_stats[assist1_player_id]['assists'] += 1
                            player_stats[assist1_player_id]['primaryAssists'] += 1
                            player_stats[assist1_player_id]['points'] += 1
                        if assist2_player_id and assist2_player_id in player_stats:
                            player_stats[assist2_player_id]['assists'] += 1
                            player_stats[assist2_player_id]['secondaryAssists'] += 1
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
                            player_stats[primary_player_id]['penaltiesTaken'] += 1
                        
                        # Check if there's a player who drew the penalty
                        drawn_by_player_id = play_details.get('drawnByPlayerId')
                        if drawn_by_player_id and drawn_by_player_id in player_stats:
                            player_stats[drawn_by_player_id]['penaltiesDrawn'] += 1
            
            # Calculate Game Score for each player
            for player_id, stats in player_stats.items():
                stats['gameScore'] = self._calculate_game_score(stats)
            
            return player_stats
            
        except (KeyError, TypeError) as e:
            print(f"Error calculating player stats from play-by-play: {e}")
            return {}
    
    def _calculate_game_score(self, player_stats):
        """Calculate Game Score using Dom Luszczyszyn formula"""
        try:
            # Game Score = 0.75×G + 0.7×A1 + 0.55×A2 + 0.075×SOG + 0.05×BLK + 0.15×PD - 0.15×PT + 0.01×FOW - 0.01×FOL + 0.15×GF - 0.15×GA
            game_score = (
                0.75 * player_stats.get('goals', 0) +
                0.7 * player_stats.get('primaryAssists', 0) +
                0.55 * player_stats.get('secondaryAssists', 0) +
                0.075 * player_stats.get('sog', 0) +
                0.05 * player_stats.get('blockedShots', 0) +
                0.15 * player_stats.get('penaltiesDrawn', 0) -
                0.15 * player_stats.get('penaltiesTaken', 0) +
                0.01 * player_stats.get('faceoffWins', 0) -
                0.01 * (player_stats.get('faceoffTotal', 0) - player_stats.get('faceoffWins', 0)) +
                0.15 * player_stats.get('goalsFor', 0) -
                0.15 * player_stats.get('goalsAgainst', 0)
            )
            return round(game_score, 2)
        except (KeyError, TypeError) as e:
            print(f"Error calculating game score: {e}")
            return 0.0
    
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
        
        # Calculate Corsi % (Shots + Blocks + Misses)
        away_corsi = away_team_stats['shotsOnGoal'] + away_team_stats['blockedShots'] + away_team_stats['missedShots']
        home_corsi = home_team_stats['shotsOnGoal'] + home_team_stats['blockedShots'] + home_team_stats['missedShots']
        away_corsi_pct = (away_corsi / (away_corsi + home_corsi) * 100) if (away_corsi + home_corsi) > 0 else 0
        home_corsi_pct = (home_corsi / (away_corsi + home_corsi) * 100) if (away_corsi + home_corsi) > 0 else 0
        
        # Create stats comparison table
        stats_data = [
            ['Statistic', away_stats['abbrev'], home_stats['abbrev']],
            ['Goals', away_stats['score'], home_stats['score']],
            ['Shots', away_stats.get('sog', 'N/A'), home_stats.get('sog', 'N/A')],
            ['Corsi %', f"{away_corsi_pct:.1f}%", f"{home_corsi_pct:.1f}%"],
            ['Power Play', f"{away_team_stats['powerPlayGoals']}/{away_team_stats['powerPlayOpportunities']}", f"{home_team_stats['powerPlayGoals']}/{home_team_stats['powerPlayOpportunities']}"],
            ['Penalty Minutes', away_team_stats['penaltyMinutes'], home_team_stats['penaltyMinutes']],
            ['Hits', away_team_stats['hits'], home_team_stats['hits']],
            ['Faceoff %', f"{away_team_stats['faceoffWins']/(away_team_stats['faceoffTotal'] + home_team_stats['faceoffTotal'])*100:.1f}%" if (away_team_stats['faceoffTotal'] + home_team_stats['faceoffTotal']) > 0 else "0.0%", f"{home_team_stats['faceoffWins']/(away_team_stats['faceoffTotal'] + home_team_stats['faceoffTotal'])*100:.1f}%" if (away_team_stats['faceoffTotal'] + home_team_stats['faceoffTotal']) > 0 else "0.0%"],
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
            # Sort by Game Score, then points, then goals
            sorted_players = sorted(away_player_stats.values(), 
                                  key=lambda x: (x['gameScore'], x['points'], x['goals']), 
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
                    player['blockedShots'],
                    player['gameScore']
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
            # Add header row
            away_headers = ["Player", "Pos", "G", "A", "P", "+/-", "PIM", "SOG", "H", "BLK", "GS"]
            away_players_with_header = [away_headers] + away_players
            away_table = Table(away_players_with_header, colWidths=[1.8*inch, 0.4*inch, 0.3*inch, 0.3*inch, 0.3*inch, 0.3*inch, 0.3*inch, 0.3*inch, 0.3*inch, 0.3*inch, 0.3*inch])
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
            # Sort by Game Score, then points, then goals
            sorted_players = sorted(home_player_stats.values(), 
                                  key=lambda x: (x['gameScore'], x['points'], x['goals']), 
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
                    player['blockedShots'],
                    player['gameScore']
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
            # Add header row
            home_headers = ["Player", "Pos", "G", "A", "P", "+/-", "PIM", "SOG", "H", "BLK", "GS"]
            home_players_with_header = [home_headers] + home_players
            home_table = Table(home_players_with_header, colWidths=[1.8*inch, 0.4*inch, 0.3*inch, 0.3*inch, 0.3*inch, 0.3*inch, 0.3*inch, 0.3*inch, 0.3*inch, 0.3*inch, 0.3*inch])
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
    
    def create_combined_shot_location_plot(self, game_data):
        """Create combined shot and goal location scatter plot for both teams"""
        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            import os
            
            play_by_play = game_data.get('play_by_play')
            if not play_by_play or 'plays' not in play_by_play:
                return None
                
            boxscore = game_data['boxscore']
            away_team = boxscore['awayTeam']
            home_team = boxscore['homeTeam']
            
            # Collect shot and goal data for both teams
            away_shots = []
            away_goals = []
            home_shots = []
            home_goals = []
            
            for play in play_by_play['plays']:
                details = play.get('details', {})
                event_type = play.get('typeDescKey', '')
                event_team = details.get('eventOwnerTeamId')
                
                if event_team == away_team['id'] and event_type in ['shot-on-goal', 'missed-shot', 'blocked-shot']:
                    x_coord = details.get('xCoord', 0)
                    y_coord = details.get('yCoord', 0)
                    if x_coord is not None and y_coord is not None:
                        away_shots.append((x_coord, y_coord))
                        
                elif event_team == away_team['id'] and event_type == 'goal':
                    x_coord = details.get('xCoord', 0)
                    y_coord = details.get('yCoord', 0)
                    if x_coord is not None and y_coord is not None:
                        away_goals.append((x_coord, y_coord))
                        
                elif event_team == home_team['id'] and event_type in ['shot-on-goal', 'missed-shot', 'blocked-shot']:
                    x_coord = details.get('xCoord', 0)
                    y_coord = details.get('yCoord', 0)
                    if x_coord is not None and y_coord is not None:
                        home_shots.append((x_coord, y_coord))
                        
                elif event_team == home_team['id'] and event_type == 'goal':
                    x_coord = details.get('xCoord', 0)
                    y_coord = details.get('yCoord', 0)
                    if x_coord is not None and y_coord is not None:
                        home_goals.append((x_coord, y_coord))
            
            if not (away_shots or away_goals or home_shots or home_goals):
                print("No shots or goals found for either team")
                return None
                
            print(f"Found {len(away_shots)} shots and {len(away_goals)} goals for {away_team['abbrev']}")
            print(f"Found {len(home_shots)} shots and {len(home_goals)} goals for {home_team['abbrev']}")
            
            # Create the plot
            plt.ioff()
            fig, ax = plt.subplots(figsize=(12, 8))
            
            # Load and display the rink image
            rink_path = '/Users/emilyfehr8/Desktop/My Analytics Work/Rink.png'
            try:
                if os.path.exists(rink_path):
                    from matplotlib.image import imread
                    rink_img = imread(rink_path)
                    # Display the rink image
                    ax.imshow(rink_img, extent=[-100, 100, -42.5, 42.5], aspect='equal', alpha=0.8)
                    print(f"Loaded rink image from: {rink_path}")
                else:
                    print(f"Rink image not found at: {rink_path}")
                    # Fallback to drawing rink outline
                    ax.plot([-100, 100], [42.5, 42.5], 'k-', linewidth=3)  # Top boards
                    ax.plot([-100, 100], [-42.5, -42.5], 'k-', linewidth=3)  # Bottom boards
                    ax.plot([-100, -100], [-42.5, 42.5], 'k-', linewidth=3)  # Left boards
                    ax.plot([100, 100], [-42.5, 42.5], 'k-', linewidth=3)  # Right boards
                    ax.plot([89, 89], [-42.5, 42.5], 'r-', linewidth=2)  # Right goal line
                    ax.plot([-89, -89], [-42.5, 42.5], 'r-', linewidth=2)  # Left goal line
                    ax.plot([25, 25], [-42.5, 42.5], 'b-', linewidth=2)  # Right blue line
                    ax.plot([-25, -25], [-42.5, 42.5], 'b-', linewidth=2)  # Left blue line
                    ax.plot([0, 0], [-42.5, 42.5], 'k-', linewidth=1)  # Center line
            except Exception as e:
                print(f"Error loading rink image: {e}")
                # Fallback to drawing rink outline
                ax.plot([-100, 100], [42.5, 42.5], 'k-', linewidth=3)  # Top boards
                ax.plot([-100, 100], [-42.5, -42.5], 'k-', linewidth=3)  # Bottom boards
                ax.plot([-100, -100], [-42.5, 42.5], 'k-', linewidth=3)  # Left boards
                ax.plot([100, 100], [-42.5, 42.5], 'k-', linewidth=3)  # Right boards
                ax.plot([89, 89], [-42.5, 42.5], 'r-', linewidth=2)  # Right goal line
                ax.plot([-89, -89], [-42.5, 42.5], 'r-', linewidth=2)  # Left goal line
                ax.plot([25, 25], [-42.5, 42.5], 'b-', linewidth=2)  # Right blue line
                ax.plot([-25, -25], [-42.5, 42.5], 'b-', linewidth=2)  # Left blue line
                ax.plot([0, 0], [-42.5, 42.5], 'k-', linewidth=1)  # Center line
            
            # Plot away team shots as light blue circles
            if away_shots:
                shot_x, shot_y = zip(*away_shots)
                ax.scatter(shot_x, shot_y, c='lightblue', alpha=0.8, s=30, 
                          label=f'{away_team["abbrev"]} Shots ({len(away_shots)})', marker='o', edgecolors='blue', linewidth=1)

            # Plot away team goals as dark blue circles
            if away_goals:
                goal_x, goal_y = zip(*away_goals)
                ax.scatter(goal_x, goal_y, c='darkblue', alpha=0.9, s=100, 
                          label=f'{away_team["abbrev"]} Goals ({len(away_goals)})', marker='o', edgecolors='navy', linewidth=2)

            # Plot home team shots as light red circles
            if home_shots:
                shot_x, shot_y = zip(*home_shots)
                ax.scatter(shot_x, shot_y, c='lightcoral', alpha=0.8, s=30, 
                          label=f'{home_team["abbrev"]} Shots ({len(home_shots)})', marker='o', edgecolors='red', linewidth=1)

            # Plot home team goals as dark red circles
            if home_goals:
                goal_x, goal_y = zip(*home_goals)
                ax.scatter(goal_x, goal_y, c='darkred', alpha=0.9, s=100, 
                          label=f'{home_team["abbrev"]} Goals ({len(home_goals)})', marker='o', edgecolors='maroon', linewidth=2)

            # Set plot properties
            ax.set_xlim(-100, 100)
            ax.set_ylim(-42.5, 42.5)
            ax.set_aspect('equal')
            ax.set_title(f'{away_team["abbrev"]} vs {home_team["abbrev"]} - Shot & Goal Locations', 
                        fontsize=18, fontweight='bold', pad=20)
            ax.set_xlabel('X Coordinate (Feet)', fontsize=14)
            ax.set_ylabel('Y Coordinate (Feet)', fontsize=14)
            ax.legend(fontsize=12, loc='upper right', framealpha=0.9)
            ax.grid(False)  # Turn off grid since we have the rink image

            # Add team labels on the rink
            ax.text(-50, 0, f'{away_team["abbrev"]}', fontsize=14, ha='center', color='blue', weight='bold')
            ax.text(50, 0, f'{home_team["abbrev"]}', fontsize=14, ha='center', color='red', weight='bold')
            
            # Save to file with a unique name to avoid conflicts
            import time
            timestamp = int(time.time() * 1000)  # milliseconds
            plot_filename = f'combined_shot_plot_{away_team["abbrev"]}_vs_{home_team["abbrev"]}_{timestamp}.png'
            abs_plot_filename = os.path.abspath(plot_filename)
            print(f"Saving combined plot to: {abs_plot_filename}")
            fig.savefig(abs_plot_filename, dpi=200, bbox_inches='tight', facecolor='white')
            plt.close(fig)
            
            # Verify file was created
            if os.path.exists(abs_plot_filename):
                print(f"Combined plot saved successfully: {abs_plot_filename}")
                print(f"File size: {os.path.getsize(abs_plot_filename)} bytes")
                return abs_plot_filename
            else:
                print(f"Failed to create combined plot: {abs_plot_filename}")
                return None
            
        except Exception as e:
            print(f"Error creating combined shot location plot: {e}")
            return None
    
    def create_advanced_metrics_section(self, game_data):
        """Create advanced metrics section using the analyzer"""
        story = []
        
        story.append(Paragraph("ADVANCED METRICS", self.subtitle_style))
        story.append(Spacer(1, 15))
        
        try:
            # Get play-by-play data
            play_by_play = game_data.get('play_by_play')
            if not play_by_play:
                story.append(Paragraph("Advanced metrics not available for this game.", self.normal_style))
                return story
            
            # Create analyzer
            analyzer = AdvancedMetricsAnalyzer(play_by_play)
            
            # Get team IDs
            boxscore = game_data['boxscore']
            away_team_id = boxscore['awayTeam']['id']
            home_team_id = boxscore['homeTeam']['id']
            
            # Generate metrics
            metrics = analyzer.generate_comprehensive_report(away_team_id, home_team_id)
            
            # Combined Advanced Metrics Table
            story.append(Paragraph("ADVANCED METRICS ANALYSIS", self.section_style))
            story.append(Spacer(1, 10))
            
            # Calculate average shots per sequence
            away_avg_shots = sum(metrics['away_team']['pressure']['shot_attempts_per_sequence'])/len(metrics['away_team']['pressure']['shot_attempts_per_sequence']) if metrics['away_team']['pressure']['shot_attempts_per_sequence'] else 0.0
            home_avg_shots = sum(metrics['home_team']['pressure']['shot_attempts_per_sequence'])/len(metrics['home_team']['pressure']['shot_attempts_per_sequence']) if metrics['home_team']['pressure']['shot_attempts_per_sequence'] else 0.0
            
            combined_data = [
                ['Category', 'Metric', boxscore['awayTeam']['abbrev'], boxscore['homeTeam']['abbrev']],
                
                # Shot Quality Analysis
                ['SHOT QUALITY', 'High Danger Shots', 
                 metrics['away_team']['shot_quality']['high_danger_shots'],
                 metrics['home_team']['shot_quality']['high_danger_shots']],
                ['', 'Total Shots', 
                 metrics['away_team']['shot_quality']['total_shots'],
                 metrics['home_team']['shot_quality']['total_shots']],
                ['', 'Shots on Goal', 
                 metrics['away_team']['shot_quality']['shots_on_goal'],
                 metrics['home_team']['shot_quality']['shots_on_goal']],
                ['', 'Shooting %', 
                 f"{metrics['away_team']['shot_quality']['shooting_percentage']:.1%}",
                 f"{metrics['home_team']['shot_quality']['shooting_percentage']:.1%}"],
                
                # Pressure Analysis
                ['PRESSURE', 'Sustained Pressure Sequences', 
                 metrics['away_team']['pressure']['sustained_pressure_sequences'],
                 metrics['home_team']['pressure']['sustained_pressure_sequences']],
                ['', 'Quick Strike Opportunities', 
                 metrics['away_team']['pressure']['quick_strike_opportunities'],
                 metrics['home_team']['pressure']['quick_strike_opportunities']],
                ['', 'Avg Shots per Sequence', 
                 f"{away_avg_shots:.1f}",
                 f"{home_avg_shots:.1f}"],
                
                # Defensive Analysis
                ['DEFENSIVE', 'Blocked Shots', 
                 metrics['away_team']['defense']['blocked_shots'],
                 metrics['home_team']['defense']['blocked_shots']],
                ['', 'Takeaways', 
                 metrics['away_team']['defense']['takeaways'],
                 metrics['home_team']['defense']['takeaways']],
                ['', 'Hits', 
                 metrics['away_team']['defense']['hits'],
                 metrics['home_team']['defense']['hits']],
                ['', 'Shot Attempts Against', 
                 metrics['away_team']['defense']['shot_attempts_against'],
                 metrics['home_team']['defense']['shot_attempts_against']],
                ['', 'High Danger Chances Against', 
                 metrics['away_team']['defense']['high_danger_chances_against'],
                 metrics['home_team']['defense']['high_danger_chances_against']]
            ]
            
            combined_table = Table(combined_data, colWidths=[1.5*inch, 2*inch, 1.2*inch, 1.2*inch])
            combined_table.setStyle(TableStyle([
                # Header row
                ('BACKGROUND', (0, 0), (-1, 0), colors.darkblue),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'RussoOne-Regular'),
                ('FONTSIZE', (0, 0), (-1, 0), 11),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
                
                # Category headers (SHOT QUALITY, PRESSURE, DEFENSIVE)
                ('BACKGROUND', (0, 1), (0, 4), colors.lightblue),  # Shot Quality
                ('BACKGROUND', (0, 5), (0, 7), colors.lightgreen),  # Pressure
                ('BACKGROUND', (0, 8), (0, 12), colors.lightgrey),  # Defensive
                ('FONTNAME', (0, 1), (0, -1), 'RussoOne-Regular'),
                ('FONTSIZE', (0, 1), (0, -1), 9),
                ('FONTWEIGHT', (0, 1), (0, -1), 'BOLD'),
                
                # Data rows
                ('BACKGROUND', (1, 1), (-1, -1), colors.white),
                ('FONTNAME', (1, 1), (-1, -1), 'RussoOne-Regular'),
                ('FONTSIZE', (1, 1), (-1, -1), 9),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                
                # Alternating row colors
                ('BACKGROUND', (1, 2), (-1, 2), colors.lightgrey),
                ('BACKGROUND', (1, 4), (-1, 4), colors.lightgrey),
                ('BACKGROUND', (1, 6), (-1, 6), colors.lightgrey),
                ('BACKGROUND', (1, 8), (-1, 8), colors.lightgrey),
                ('BACKGROUND', (1, 10), (-1, 10), colors.lightgrey),
                ('BACKGROUND', (1, 12), (-1, 12), colors.lightgrey),
            ]))
            
            story.append(combined_table)
            story.append(Spacer(1, 20))
            
        except Exception as e:
            print(f"Error creating advanced metrics: {e}")
            story.append(Paragraph("Advanced metrics could not be calculated for this game.", self.normal_style))
        
        return story
    
    def create_visualizations(self, game_data):
        """Create shot location visualizations"""
        story = []
        
        story.append(Paragraph("SHOT LOCATION ANALYSIS", self.subtitle_style))
        story.append(Spacer(1, 15))
        
        try:
            import os
            boxscore = game_data['boxscore']
            away_team = boxscore['awayTeam']
            home_team = boxscore['homeTeam']
            
            # Create combined shot location scatter plot for both teams
            try:
                # Create combined plot
                combined_plot = self.create_combined_shot_location_plot(game_data)
                
                # Add a small delay to ensure files are written
                import time
                time.sleep(0.5)
                
                if combined_plot and os.path.exists(combined_plot):
                    print(f"Adding combined plot from file: {combined_plot}")
                    story.append(Paragraph(f"{away_team['abbrev']} vs {home_team['abbrev']} - Shot & Goal Locations", self.section_style))
                    try:
                        combined_image = Image(combined_plot, width=8*inch, height=5.3*inch)
                        combined_image.hAlign = 'CENTER'
                        story.append(combined_image)
                        story.append(Spacer(1, 20))
                        print("Successfully added combined plot to PDF")
                        
                        # Store the file path for cleanup later
                        if not hasattr(self, 'temp_plot_files'):
                            self.temp_plot_files = []
                        self.temp_plot_files.append(combined_plot)
                    except Exception as e:
                        print(f"Error adding combined plot to PDF: {e}")
                        story.append(Paragraph("Combined shot location plot could not be added to PDF.", self.normal_style))
                else:
                    print(f"Combined shot location plot failed")
                    story.append(Paragraph("Shot location analysis could not be generated.", self.normal_style))
            except Exception as e:
                print(f"Error creating combined plot: {e}")
                story.append(Paragraph("Combined shot location plot could not be created.", self.normal_style))
            
        except Exception as e:
            print(f"Error creating shot location plots: {e}")
            story.append(Paragraph("Shot location analysis could not be created for this game.", self.normal_style))
        
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
        story.extend(self.create_advanced_metrics_section(game_data))
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
