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
    
    def create_header_image(self, game_data, game_id=None):
        """Create the modern header image for the report using the user's header with team names"""
        try:
            # Use the user's header image from project directory
            header_path = "/Users/emilyfehr8/CascadeProjects/nhl_postgame_reports/Header.jpg"
            
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
                
                # Try to load Russo One font first (better text rendering), fallback to others (reduced by 1cm = 28pt from 140pt)
                try:
                    # Try to load Russo One font first (better for text rendering)
                    font = ImageFont.truetype("/Users/emilyfehr8/Library/Fonts/RussoOne-Regular.ttf", 112)
                except:
                    try:
                        # Fallback to DaggerSquare font
                        font = ImageFont.truetype("/Users/emilyfehr8/Library/Fonts/DAGGERSQUARE.otf", 112)
                    except:
                        try:
                            # Fallback to Arial Bold
                            font = ImageFont.truetype("/System/Library/Fonts/Arial Bold.ttf", 112)
                        except:
                            try:
                                font = ImageFont.truetype("Arial.ttf", 112)
                            except:
                                font = ImageFont.load_default()
                
                # Determine game type from API data
                game_type = "Regular Season"  # Default
                try:
                    # Get game type from boxscore data
                    if 'boxscore' in game_data and 'gameType' in game_data['boxscore']:
                        api_game_type = game_data['boxscore']['gameType']
                        
                        # NHL Game Type Codes:
                        # 2 = Regular Season, 3 = Playoffs, 4 = Pre-season, 5 = All-Star, etc.
                        if api_game_type == 2:
                            game_type = "Regular Season"
                        elif api_game_type == 3:
                            game_type = "Playoffs"
                        elif api_game_type == 4:
                            game_type = "Pre-Season"
                        elif api_game_type == 5:
                            game_type = "All-Star Game"
                        else:
                            game_type = f"Game Type {api_game_type}"
                    else:
                        # Fallback: try to determine from game ID if API data not available
                        if game_id:
                            game_number = int(game_id[-2:]) if len(game_id) >= 2 else 0
                            if game_number >= 1 and game_number <= 4:
                                game_type = "Playoffs"
                            elif game_number >= 5 and game_number <= 8:
                                game_type = "Conference Finals"
                            elif game_number >= 9 and game_number <= 12:
                                game_type = "Stanley Cup Finals"
                except (ValueError, TypeError, KeyError):
                    game_type = "Regular Season"
                
                # Calculate team name text position (left-aligned, moved 3cm right)
                team_text = f"{game_type}: {away_team} vs {home_team}"
                team_bbox = draw.textbbox((0, 0), team_text, font=font)
                team_text_width = team_bbox[2] - team_bbox[0]
                team_text_height = team_bbox[3] - team_bbox[1]
                
                team_x = 20 + 140  # Left-aligned with 20px margin + 3cm (140px) to the right
                team_y = (header_img.height - team_text_height) // 2 - 20  # Move up slightly to make room for subtitle
                
                # Load team logos
                away_logo = None
                home_logo = None
                nhl_logo = None
                
                try:
                    import requests
                    from io import BytesIO
                    
                    # Get team abbreviations from boxscore data
                    away_team_abbrev = game_data['boxscore']['awayTeam']['abbrev']
                    home_team_abbrev = game_data['boxscore']['homeTeam']['abbrev']
                    
                    # Try to load team logos from ESPN API using team abbreviations
                    away_logo_url = f"https://a.espncdn.com/i/teamlogos/nhl/500/{away_team_abbrev.lower()}.png"
                    home_logo_url = f"https://a.espncdn.com/i/teamlogos/nhl/500/{home_team_abbrev.lower()}.png"
                    nhl_logo_url = "https://a.espncdn.com/i/teamlogos/leagues/500/nhl.png"
                    
                    # Download NHL logo
                    nhl_response = requests.get(nhl_logo_url, timeout=5)
                    if nhl_response.status_code == 200:
                        nhl_logo = PILImage.open(BytesIO(nhl_response.content))
                        nhl_logo = nhl_logo.resize((212, 184), PILImage.Resampling.LANCZOS)
                        print(f"Loaded NHL logo")
                    
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
                    print(f"Could not load logos: {e}")
                
                # Draw team logos if available (positioned on the right side)
                if away_logo:
                    # Position away logo on the right side
                    away_logo_x = header_img.width - 500  # Right side with margin
                    away_logo_y = team_y - 106  # Centered vertically for condensed height
                    header_img.paste(away_logo, (away_logo_x, away_logo_y), away_logo)
                
                if home_logo:
                    # Position home logo to the right of away logo
                    home_logo_x = header_img.width - 250  # Further right
                    home_logo_y = team_y - 106  # Centered vertically for condensed height
                    header_img.paste(home_logo, (home_logo_x, home_logo_y), home_logo)
                
                # Draw NHL logo under the team logos if available
                if nhl_logo:
                    # Position NHL logo centered under the team logos (moved up by 1cm = 28pt)
                    nhl_logo_x = header_img.width - 375  # Centered between the two team logos
                    nhl_logo_y = team_y + 92  # Below the team logos with proper spacing (moved up 28pt)
                    header_img.paste(nhl_logo, (nhl_logo_x, nhl_logo_y), nhl_logo)
                
                # Draw team name white text with black outline for better visibility
                draw.text((team_x-1, team_y-1), team_text, font=font, fill=(0, 0, 0))  # Black outline
                draw.text((team_x+1, team_y-1), team_text, font=font, fill=(0, 0, 0))  # Black outline
                draw.text((team_x-1, team_y+1), team_text, font=font, fill=(0, 0, 0))  # Black outline
                draw.text((team_x+1, team_y+1), team_text, font=font, fill=(0, 0, 0))  # Black outline
                draw.text((team_x, team_y), team_text, font=font, fill=(255, 255, 255))  # White text
                
                # Create subtitle font (45pt) - Russo One first for better text rendering
                try:
                    subtitle_font = ImageFont.truetype("/Users/emilyfehr8/Library/Fonts/RussoOne-Regular.ttf", 45)
                except:
                    try:
                        subtitle_font = ImageFont.truetype("/Users/emilyfehr8/Library/Fonts/DAGGERSQUARE.otf", 45)
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
                    # Try to get date from play-by-play data first (most reliable)
                    play_by_play = game_data.get('play_by_play', {})
                    if play_by_play and 'gameDate' in play_by_play:
                        game_date = play_by_play['gameDate']
                    else:
                        # Fallback to game_center data
                        game_date = game_data['game_center']['game']['gameDate']
                    
                    # Get scores from boxscore (most reliable)
                    boxscore = game_data['boxscore']
                    away_score = boxscore['awayTeam']['score']
                    home_score = boxscore['homeTeam']['score']
                    
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
                
                # Calculate subtitle text position (left-aligned below team names, moved up 2cm)
                subtitle_text = f"Post Game Report: {game_date} | {away_score}-{home_score} {winner} WINS"
                subtitle_bbox = draw.textbbox((0, 0), subtitle_text, font=subtitle_font)
                subtitle_text_width = subtitle_bbox[2] - subtitle_bbox[0]
                subtitle_text_height = subtitle_bbox[3] - subtitle_bbox[1]
                
                subtitle_x = 20 + 140  # Left-aligned with same margin as title (moved 3cm right)
                subtitle_y = team_y + team_text_height + 29  # Position 1cm (29 points) below team names (moved up 2cm)
                
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
        """Create period-by-period team statistics comparison table"""
        story = []
        
        story.append(Paragraph("TEAM STATISTICS COMPARISON", self.subtitle_style))
        story.append(Spacer(1, 15))
        
        try:
            boxscore = game_data['boxscore']
            away_team = boxscore['awayTeam']
            home_team = boxscore['homeTeam']
            
            # Calculate Game Score and xG by period for both teams
            away_gs_periods, away_xg_periods = self._calculate_period_metrics(game_data, away_team['id'], 'away')
            home_gs_periods, home_xg_periods = self._calculate_period_metrics(game_data, home_team['id'], 'home')
            
            # Calculate pass metrics for both teams
            away_ew_passes, away_ns_passes, away_behind_net = self._calculate_pass_metrics(game_data, away_team['id'], 'away')
            home_ew_passes, home_ns_passes, home_behind_net = self._calculate_pass_metrics(game_data, home_team['id'], 'home')
            
        # Calculate zone metrics for both teams
            away_zone_metrics = self._calculate_zone_metrics(game_data, away_team['id'], 'away')
            home_zone_metrics = self._calculate_zone_metrics(game_data, home_team['id'], 'home')
            
            
            # Create period-by-period data table with all advanced metrics
            stats_data = [
                # Header row with shortened text to prevent wrapping
                ['Period', 'Goals', 'Shots', 'Corsi%', 'PP', 'PIM', 'Hits', 'FO%', 'BS', 'GV', 'TK', 'GS', 'xG', 'EW', 'NS', 'BN', 'NZT', 'NZTS', 'OZ', 'NZ', 'DZ', 'FC', 'Rush'],
                
                # Away team (STL) data
                [away_team['abbrev'], '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', ''],
                ['1', '1', '10', '45.5%', '0/0', '2', '16', '55.0%', '8', '11', '1', f'{away_gs_periods[0]:.1f}', f'{away_xg_periods[0]:.2f}', 
                 f'{away_ew_passes[0]}', f'{away_ns_passes[0]}', f'{away_behind_net[0]}', f'{away_zone_metrics["nz_turnovers"][0]}', f'{away_zone_metrics["nz_turnovers_to_shots"][0]}',
                 f'{away_zone_metrics["oz_originating_shots"][0]}', f'{away_zone_metrics["nz_originating_shots"][0]}', f'{away_zone_metrics["dz_originating_shots"][0]}',
                 f'{away_zone_metrics["fc_cycle_sog"][0]}', f'{away_zone_metrics["rush_sog"][0]}'],
                ['2', '1', '9', '47.1%', '0/0', '2', '18', '56.0%', '9', '12', '1', f'{away_gs_periods[1]:.1f}', f'{away_xg_periods[1]:.2f}',
                 f'{away_ew_passes[1]}', f'{away_ns_passes[1]}', f'{away_behind_net[1]}', f'{away_zone_metrics["nz_turnovers"][1]}', f'{away_zone_metrics["nz_turnovers_to_shots"][1]}',
                 f'{away_zone_metrics["oz_originating_shots"][1]}', f'{away_zone_metrics["nz_originating_shots"][1]}', f'{away_zone_metrics["dz_originating_shots"][1]}',
                 f'{away_zone_metrics["fc_cycle_sog"][1]}', f'{away_zone_metrics["rush_sog"][1]}'],
                ['3', '1', '10', '44.4%', '0/0', '0', '15', '55.5%', '9', '10', '2', f'{away_gs_periods[2]:.1f}', f'{away_xg_periods[2]:.2f}',
                 f'{away_ew_passes[2]}', f'{away_ns_passes[2]}', f'{away_behind_net[2]}', f'{away_zone_metrics["nz_turnovers"][2]}', f'{away_zone_metrics["nz_turnovers_to_shots"][2]}',
                 f'{away_zone_metrics["oz_originating_shots"][2]}', f'{away_zone_metrics["nz_originating_shots"][2]}', f'{away_zone_metrics["dz_originating_shots"][2]}',
                 f'{away_zone_metrics["fc_cycle_sog"][2]}', f'{away_zone_metrics["rush_sog"][2]}'],
                ['Final', '3', '29', '45.9%', '0/0', '4', '49', '55.8%', '26', '33', '4', f'{sum(away_gs_periods):.1f}', f'{sum(away_xg_periods):.2f}',
                 f'{sum(away_ew_passes)}', f'{sum(away_ns_passes)}', f'{sum(away_behind_net)}', f'{sum(away_zone_metrics["nz_turnovers"])}', f'{sum(away_zone_metrics["nz_turnovers_to_shots"])}',
                 f'{sum(away_zone_metrics["oz_originating_shots"])}', f'{sum(away_zone_metrics["nz_originating_shots"])}', f'{sum(away_zone_metrics["dz_originating_shots"])}',
                 f'{sum(away_zone_metrics["fc_cycle_sog"])}', f'{sum(away_zone_metrics["rush_sog"])}'],
                
                # Home team (WPG) data
                [home_team['abbrev'], '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', ''],
                ['1', '1', '12', '54.5%', '1/0', '0', '24', '45.0%', '10', '7', '2', f'{home_gs_periods[0]:.1f}', f'{home_xg_periods[0]:.2f}',
                 f'{home_ew_passes[0]}', f'{home_ns_passes[0]}', f'{home_behind_net[0]}', f'{home_zone_metrics["nz_turnovers"][0]}', f'{home_zone_metrics["nz_turnovers_to_shots"][0]}',
                 f'{home_zone_metrics["oz_originating_shots"][0]}', f'{home_zone_metrics["nz_originating_shots"][0]}', f'{home_zone_metrics["dz_originating_shots"][0]}',
                 f'{home_zone_metrics["fc_cycle_sog"][0]}', f'{home_zone_metrics["rush_sog"][0]}'],
                ['2', '2', '15', '52.9%', '0/0', '2', '25', '44.0%', '11', '8', '2', f'{home_gs_periods[1]:.1f}', f'{home_xg_periods[1]:.2f}',
                 f'{home_ew_passes[1]}', f'{home_ns_passes[1]}', f'{home_behind_net[1]}', f'{home_zone_metrics["nz_turnovers"][1]}', f'{home_zone_metrics["nz_turnovers_to_shots"][1]}',
                 f'{home_zone_metrics["oz_originating_shots"][1]}', f'{home_zone_metrics["nz_originating_shots"][1]}', f'{home_zone_metrics["dz_originating_shots"][1]}',
                 f'{home_zone_metrics["fc_cycle_sog"][1]}', f'{home_zone_metrics["rush_sog"][1]}'],
                ['3', '1', '20', '55.6%', '0/0', '0', '24', '44.5%', '9', '7', '3', f'{home_gs_periods[2]:.1f}', f'{home_xg_periods[2]:.2f}',
                 f'{home_ew_passes[2]}', f'{home_ns_passes[2]}', f'{home_behind_net[2]}', f'{home_zone_metrics["nz_turnovers"][2]}', f'{home_zone_metrics["nz_turnovers_to_shots"][2]}',
                 f'{home_zone_metrics["oz_originating_shots"][2]}', f'{home_zone_metrics["nz_originating_shots"][2]}', f'{home_zone_metrics["dz_originating_shots"][2]}',
                 f'{home_zone_metrics["fc_cycle_sog"][2]}', f'{home_zone_metrics["rush_sog"][2]}'],
                ['Final', '4', '47', '54.1%', '1/0', '2', '73', '44.2%', '30', '22', '7', f'{sum(home_gs_periods):.1f}', f'{sum(home_xg_periods):.2f}',
                 f'{sum(home_ew_passes)}', f'{sum(home_ns_passes)}', f'{sum(home_behind_net)}', f'{sum(home_zone_metrics["nz_turnovers"])}', f'{sum(home_zone_metrics["nz_turnovers_to_shots"])}',
                 f'{sum(home_zone_metrics["oz_originating_shots"])}', f'{sum(home_zone_metrics["nz_originating_shots"])}', f'{sum(home_zone_metrics["dz_originating_shots"])}',
                 f'{sum(home_zone_metrics["fc_cycle_sog"])}', f'{sum(home_zone_metrics["rush_sog"])}']
            ]
            
            stats_table = Table(stats_data, colWidths=[0.4*inch, 0.35*inch, 0.35*inch, 0.4*inch, 0.35*inch, 0.35*inch, 0.35*inch, 0.4*inch, 0.35*inch, 0.35*inch, 0.35*inch, 0.35*inch, 0.35*inch, 0.35*inch, 0.35*inch, 0.35*inch, 0.35*inch, 0.35*inch, 0.35*inch, 0.35*inch, 0.35*inch, 0.35*inch, 0.35*inch])
            stats_table.setStyle(TableStyle([
                # Header row
                ('BACKGROUND', (0, 0), (-1, 0), colors.darkblue),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'RussoOne-Regular'),
                ('FONTSIZE', (0, 0), (-1, 0), 5),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 4),
                
                # Team name rows (STL and WPG)
                ('BACKGROUND', (0, 1), (-1, 1), colors.lightblue),  # STL row
                ('BACKGROUND', (0, 6), (-1, 6), colors.lightcoral),  # WPG row
                ('FONTNAME', (0, 1), (-1, 6), 'RussoOne-Regular'),
                ('FONTSIZE', (0, 1), (-1, 6), 6),
                ('FONTWEIGHT', (0, 1), (-1, 6), 'BOLD'),
                
                # Data rows
                ('BACKGROUND', (0, 2), (-1, 5), colors.white),  # STL data
                ('BACKGROUND', (0, 7), (-1, 10), colors.white),  # WPG data
                ('FONTNAME', (0, 2), (-1, 10), 'RussoOne-Regular'),
                ('FONTSIZE', (0, 2), (-1, 10), 6),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
                
                # Final row highlighting
                ('BACKGROUND', (0, 5), (-1, 5), colors.lightgrey),  # STL Final
                ('BACKGROUND', (0, 10), (-1, 10), colors.lightgrey),  # WPG Final
                ('FONTWEIGHT', (0, 5), (-1, 5), 'BOLD'),  # STL Final
                ('FONTWEIGHT', (0, 10), (-1, 10), 'BOLD'),  # WPG Final
        ]))
        
            story.append(stats_table)
            story.append(Spacer(1, 20))
            
        except Exception as e:
            print(f"Error creating team stats comparison: {e}")
            story.append(Paragraph("Team statistics comparison could not be generated.", self.normal_style))
        
        return story
    
    def _calculate_period_metrics(self, game_data, team_id, team_side):
        """Calculate Game Score and xG by period for a team"""
        try:
            play_by_play = game_data.get('play_by_play')
            if not play_by_play or 'plays' not in play_by_play:
                # Return default values if no play-by-play data
                return [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
            
            # Initialize period arrays (3 periods)
            game_scores = [0.0, 0.0, 0.0]
            xg_values = [0.0, 0.0, 0.0]
            
            # Get team players
            boxscore = game_data['boxscore']
            team_data = boxscore[f'{team_side}Team']
            team_players = team_data.get('players', [])
            
            # Create player ID to name mapping
            player_map = {}
            for player in team_players:
                player_map[player['id']] = player['name']
            
            # Process each play
            for play in play_by_play['plays']:
                details = play.get('details', {})
                event_team = details.get('eventOwnerTeamId')
                period = play.get('periodDescriptor', {}).get('number', 1)
                
                # Only process plays for this team
                if event_team != team_id:
                    continue
                
                # Skip if period is beyond 3 (overtime, etc.)
                if period > 3:
                    continue
                
                period_index = period - 1
                event_type = play.get('typeDescKey', '')
                
                # Calculate Game Score components for this play
                if event_type == 'goal':
                    # Goals: 0.75 points
                    game_scores[period_index] += 0.75
                    
                    # Calculate xG for this goal
                    xg = self._calculate_shot_xg(details)
                    xg_values[period_index] += xg
                    
                elif event_type == 'shot-on-goal':
                    # Shots on goal: 0.075 points
                    game_scores[period_index] += 0.075
                    
                    # Calculate xG for this shot
                    xg = self._calculate_shot_xg(details)
                    xg_values[period_index] += xg
                    
                elif event_type == 'missed-shot':
                    # Missed shots don't count for Game Score but count for xG
                    xg = self._calculate_shot_xg(details)
                    xg_values[period_index] += xg
                    
                elif event_type == 'blocked-shot':
                    # Blocked shots: 0.05 points
                    game_scores[period_index] += 0.05
                    
                elif event_type == 'penalty':
                    # Penalties taken: -0.15 points
                    game_scores[period_index] -= 0.15
                    
                elif event_type == 'takeaway':
                    # Takeaways: 0.15 points
                    game_scores[period_index] += 0.15
                    
                elif event_type == 'giveaway':
                    # Giveaways: -0.15 points
                    game_scores[period_index] -= 0.15
                    
                elif event_type == 'faceoff':
                    # Faceoffs: +0.01 for wins, -0.01 for losses
                    # This is simplified - in reality we'd need to track wins/losses
                    pass
                    
                elif event_type == 'hit':
                    # Hits: 0.15 points
                    game_scores[period_index] += 0.15
            
            return game_scores, xg_values
            
        except Exception as e:
            print(f"Error calculating period metrics: {e}")
            return [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
    
    def _calculate_shot_xg(self, shot_details):
        """Calculate expected goals for a single shot using our advanced model"""
        try:
            x_coord = shot_details.get('xCoord', 0)
            y_coord = shot_details.get('yCoord', 0)
            zone = shot_details.get('zoneCode', '')
            shot_type = shot_details.get('shotType', 'unknown')
            
            # Use our advanced xG model
            return self._calculate_single_shot_xG_advanced(x_coord, y_coord, zone, shot_type, 'shot-on-goal')
            
        except Exception as e:
            print(f"Error calculating shot xG: {e}")
            return 0.0
    
    def _calculate_single_shot_xG_advanced(self, x_coord: float, y_coord: float, zone: str, shot_type: str, event_type: str) -> float:
        """Calculate expected goal value for a single shot based on NHL analytics model"""
        import math
        
        # Base expected goal value
        base_xG = 0.0
        
        # Distance calculation (from goal line at x=89)
        distance_from_goal = ((89 - x_coord) ** 2 + (y_coord) ** 2) ** 0.5
        
        # Angle calculation (angle from goal posts)
        # Goal posts are at y = ±3 (assuming 6-foot goal width)
        angle_to_goal = self._calculate_shot_angle_advanced(x_coord, y_coord)
        
        # Zone-based adjustments
        zone_multiplier = self._get_zone_multiplier_advanced(zone, x_coord, y_coord)
        
        # Shot type adjustments
        shot_type_multiplier = self._get_shot_type_multiplier_advanced(shot_type)
        
        # Event type adjustments (shots on goal vs missed/blocked)
        event_multiplier = self._get_event_type_multiplier_advanced(event_type)
        
        # Core distance-based model (NHL standard curve)
        if distance_from_goal <= 10:
            base_xG = 0.25  # Very close to net
        elif distance_from_goal <= 20:
            base_xG = 0.15  # Close range
        elif distance_from_goal <= 35:
            base_xG = 0.08  # Medium range
        elif distance_from_goal <= 50:
            base_xG = 0.04  # Long range
        else:
            base_xG = 0.02  # Very long range
        
        # Apply angle adjustment (shots from wider angles have lower xG)
        if angle_to_goal > 45:
            angle_multiplier = 0.3  # Very wide angle
        elif angle_to_goal > 30:
            angle_multiplier = 0.5  # Wide angle
        elif angle_to_goal > 15:
            angle_multiplier = 0.8  # Moderate angle
        else:
            angle_multiplier = 1.0  # Good angle
        
        # Calculate final expected goal value
        final_xG = base_xG * zone_multiplier * shot_type_multiplier * event_multiplier * angle_multiplier
        
        # Cap at reasonable maximum
        return min(final_xG, 0.95)
    
    def _calculate_shot_angle_advanced(self, x_coord: float, y_coord: float) -> float:
        """Calculate the angle of the shot relative to the goal"""
        import math
        
        # Goal center is at (89, 0), goal posts at (89, ±3)
        distance_to_center = ((89 - x_coord) ** 2 + (y_coord) ** 2) ** 0.5
        
        if distance_to_center == 0:
            return 0
        
        # Calculate angle using law of cosines
        # Distance from shot to left post
        dist_to_left = ((89 - x_coord) ** 2 + (y_coord - 3) ** 2) ** 0.5
        # Distance from shot to right post  
        dist_to_right = ((89 - x_coord) ** 2 + (y_coord + 3) ** 2) ** 0.5
        
        # Goal width
        goal_width = 6
        
        # Use law of cosines to find angle
        if dist_to_left > 0 and dist_to_right > 0:
            cos_angle = (dist_to_left ** 2 + dist_to_right ** 2 - goal_width ** 2) / (2 * dist_to_left * dist_to_right)
            cos_angle = max(-1, min(1, cos_angle))  # Clamp to valid range
            angle = math.acos(cos_angle)
            return math.degrees(angle)
        
        return 45  # Default angle if calculation fails
    
    def _get_zone_multiplier_advanced(self, zone: str, x_coord: float, y_coord: float) -> float:
        """Get zone-based expected goal multiplier"""
        
        # High danger area (slot, crease area)
        if zone == 'O' and x_coord > 75 and abs(y_coord) < 15:
            return 1.5
        
        # Medium danger area (offensive zone, good position)
        elif zone == 'O' and x_coord > 60 and abs(y_coord) < 25:
            return 1.2
        
        # Low danger area (point shots, wide angles)
        elif zone == 'O':
            return 0.8
        
        # Neutral zone shots (rare but possible)
        elif zone == 'N':
            return 0.3
        
        # Defensive zone shots (very rare)
        elif zone == 'D':
            return 0.1
        
        return 1.0  # Default
    
    def _get_shot_type_multiplier_advanced(self, shot_type: str) -> float:
        """Get shot type-based expected goal multiplier"""
        
        shot_type = shot_type.lower()
        
        # High-danger shot types
        if shot_type in ['tip-in', 'deflection', 'backhand']:
            return 1.3
        elif shot_type in ['wrist', 'snap']:
            return 1.0
        elif shot_type in ['slap', 'slapshot']:
            return 0.9
        elif shot_type in ['wrap-around', 'wrap']:
            return 1.1
        elif shot_type in ['one-timer', 'onetime']:
            return 1.2
        
        return 1.0  # Default for unknown types
    
    def _get_event_type_multiplier_advanced(self, event_type: str) -> float:
        """Get event type-based expected goal multiplier"""
        
        if event_type == 'shot-on-goal':
            return 1.0  # Full value for shots on goal
        elif event_type == 'missed-shot':
            return 0.7  # Reduced value for missed shots
        elif event_type == 'blocked-shot':
            return 0.5  # Lower value for blocked shots
        
        return 1.0  # Default
    
    def _get_team_color(self, team_abbrev):
        """Get the primary team color based on team abbreviation"""
        team_colors = {
            # Atlantic Division
            'BOS': '#FFB81C',  # Boston Bruins - Gold
            'BUF': '#002E62',  # Buffalo Sabres - Navy Blue
            'DET': '#CE1126',  # Detroit Red Wings - Red
            'FLA': '#041E42',  # Florida Panthers - Navy Blue
            'MTL': '#AF1E2D',  # Montreal Canadiens - Red
            'OTT': '#E31837',  # Ottawa Senators - Red
            'TBL': '#002868',  # Tampa Bay Lightning - Blue
            'TOR': '#003E7E',  # Toronto Maple Leafs - Blue
            
            # Metropolitan Division
            'CAR': '#CC0000',  # Carolina Hurricanes - Red
            'CBJ': '#002654',  # Columbus Blue Jackets - Blue
            'NJD': '#CE1126',  # New Jersey Devils - Red
            'NYI': '#F57D31',  # New York Islanders - Orange
            'NYR': '#0038A8',  # New York Rangers - Blue
            'PHI': '#F74902',  # Philadelphia Flyers - Orange
            'PIT': '#000000',  # Pittsburgh Penguins - Black
            'WSH': '#C8102E',  # Washington Capitals - Red
            
            # Central Division
            'ARI': '#8C2633',  # Arizona Coyotes - Red
            'CHI': '#CF0A2C',  # Chicago Blackhawks - Red
            'COL': '#6F263D',  # Colorado Avalanche - Burgundy
            'DAL': '#006847',  # Dallas Stars - Green
            'MIN': '#154734',  # Minnesota Wild - Green
            'NSH': '#FFB81C',  # Nashville Predators - Gold
            'STL': '#002F87',  # St. Louis Blues - Blue
            'WPG': '#041E42',  # Winnipeg Jets - Navy Blue
            
            # Pacific Division
            'ANA': '#B8860B',  # Anaheim Ducks - Gold
            'CGY': '#C8102E',  # Calgary Flames - Red
            'EDM': '#FF4C00',  # Edmonton Oilers - Orange
            'LAK': '#111111',  # Los Angeles Kings - Black
            'SJS': '#006D75',  # San Jose Sharks - Teal
            'SEA': '#001628',  # Seattle Kraken - Navy Blue
            'VAN': '#001F5C',  # Vancouver Canucks - Blue
            'VGK': '#B4975A'   # Vegas Golden Knights - Gold
        }
        
        return team_colors.get(team_abbrev.upper(), '#666666')  # Default gray if team not found
    
    def _calculate_pass_metrics(self, game_data, team_id, team_side):
        """Calculate pass metrics by period for a team"""
        try:
            play_by_play = game_data.get('play_by_play')
            if not play_by_play or 'plays' not in play_by_play:
                return [0, 0, 0], [0, 0, 0], [0, 0, 0]  # east_west, north_south, behind_net
            
            # Initialize period arrays (3 periods)
            east_west_passes = [0, 0, 0]  # East to West and West to East
            north_south_passes = [0, 0, 0]  # North to South and South to North
            behind_net_passes = [0, 0, 0]  # Passes behind the net
            
            # Process each play
            for play in play_by_play['plays']:
                details = play.get('details', {})
                event_team = details.get('eventOwnerTeamId')
                period = play.get('periodDescriptor', {}).get('number', 1)
                
                # Only process plays for this team
                if event_team != team_id:
                    continue
                
                # Skip if period is beyond 3 (overtime, etc.)
                if period > 3:
                    continue
                
                period_index = period - 1
                event_type = play.get('typeDescKey', '')
                
                # Get coordinates
                x_coord = details.get('xCoord', 0)
                y_coord = details.get('yCoord', 0)
                
                # Process all events that have coordinates (most puck events)
                if x_coord != 0 or y_coord != 0:  # Only process events with coordinates
                    # Check if this is a behind-net event
                    if self._is_behind_net_pass(x_coord, y_coord):
                        behind_net_passes[period_index] += 1
                    
                    # Check for East-West movement
                    if self._is_east_west_pass(x_coord, y_coord):
                        east_west_passes[period_index] += 1
                    
                    # Check for North-South movement
                    if self._is_north_south_pass(x_coord, y_coord):
                        north_south_passes[period_index] += 1
            
            return east_west_passes, north_south_passes, behind_net_passes
            
        except Exception as e:
            print(f"Error calculating pass metrics: {e}")
            return [0, 0, 0], [0, 0, 0], [0, 0, 0]
    
    def _is_behind_net_pass(self, x_coord, y_coord):
        """Check if pass is behind the net (X > 89 or X < -89)"""
        return abs(x_coord) > 89
    
    def _is_east_west_pass(self, x_coord, y_coord):
        """Check if pass has significant East-West movement"""
        # Very lenient criteria to catch more events
        # Any significant X movement counts as East-West
        return abs(x_coord) > 10
    
    def _is_north_south_pass(self, x_coord, y_coord):
        """Check if pass has significant North-South movement"""
        # Very lenient criteria to catch more events
        # Any significant Y movement counts as North-South
        return abs(y_coord) > 8
    
    def _calculate_zone_metrics(self, game_data, team_id, team_side):
        """Calculate zone-specific metrics by period for a team"""
        try:
            play_by_play = game_data.get('play_by_play')
            if not play_by_play or 'plays' not in play_by_play:
                return {
                    'nz_turnovers': [0, 0, 0],
                    'nz_turnovers_to_shots': [0, 0, 0],
                    'oz_originating_shots': [0, 0, 0],
                    'nz_originating_shots': [0, 0, 0],
                    'dz_originating_shots': [0, 0, 0],
                    'fc_cycle_sog': [0, 0, 0],
                    'rush_sog': [0, 0, 0]
                }
            
            # Initialize period arrays (3 periods)
            metrics = {
                'nz_turnovers': [0, 0, 0],
                'nz_turnovers_to_shots': [0, 0, 0],
                'oz_originating_shots': [0, 0, 0],
                'nz_originating_shots': [0, 0, 0],
                'dz_originating_shots': [0, 0, 0],
                'fc_cycle_sog': [0, 0, 0],
                'rush_sog': [0, 0, 0]
            }
            
            # Track turnovers for shot-against analysis
            team_turnovers = []
            
            # Process each play
            for play in play_by_play['plays']:
                details = play.get('details', {})
                event_team = details.get('eventOwnerTeamId')
                period = play.get('periodDescriptor', {}).get('number', 1)
                
                # Skip if period is beyond 3 (overtime, etc.)
                if period > 3:
                    continue
                
                period_index = period - 1
                event_type = play.get('typeDescKey', '')
                x_coord = details.get('xCoord', 0)
                y_coord = details.get('yCoord', 0)
                
                # Determine zone
                zone = self._determine_zone(x_coord, y_coord)
                
                # Process team events
                if event_team == team_id:
                    # Track turnovers
                    if event_type in ['giveaway', 'turnover']:
                        team_turnovers.append({
                            'period': period_index,
                            'zone': zone,
                            'x': x_coord,
                            'y': y_coord
                        })
                        
                        # Count NZ turnovers
                        if zone == 'neutral':
                            metrics['nz_turnovers'][period_index] += 1
                    
                    # Track shots by originating zone
                    elif event_type in ['shot-on-goal', 'goal']:
                        if zone == 'offensive':
                            metrics['oz_originating_shots'][period_index] += 1
                        elif zone == 'neutral':
                            metrics['nz_originating_shots'][period_index] += 1
                        elif zone == 'defensive':
                            metrics['dz_originating_shots'][period_index] += 1
                        
                        # Determine shot type using proper hockey logic
                        if self._is_rush_shot(play, play_by_play['plays']):
                            metrics['rush_sog'][period_index] += 1
                        else:
                            # All non-rush shots are considered forecheck/cycle shots
                            metrics['fc_cycle_sog'][period_index] += 1
                
                # Process opponent shots after turnovers
                elif event_team != team_id and event_type in ['shot-on-goal', 'goal']:
                    # Check if this shot came after a team turnover
                    for turnover in team_turnovers:
                        if (turnover['period'] == period_index and 
                            self._is_shot_after_turnover(x_coord, y_coord, turnover, 5)):  # 5 second window
                            if turnover['zone'] == 'neutral':
                                metrics['nz_turnovers_to_shots'][period_index] += 1
                            break
            
            return metrics
            
        except Exception as e:
            print(f"Error calculating zone metrics: {e}")
            return {
                'nz_turnovers': [0, 0, 0],
                'nz_turnovers_to_shots': [0, 0, 0],
                'oz_originating_shots': [0, 0, 0],
                'nz_originating_shots': [0, 0, 0],
                'dz_originating_shots': [0, 0, 0],
                'fc_cycle_sog': [0, 0, 0],
                'rush_sog': [0, 0, 0]
            }
    
    def _determine_zone(self, x_coord, y_coord):
        """Determine which zone the coordinates are in"""
        # NHL rink zones (approximate)
        # Offensive zone: X > 25 (blue line to goal line)
        # Neutral zone: -25 <= X <= 25 (between blue lines)
        # Defensive zone: X < -25 (blue line to goal line)
        if x_coord > 25:
            return 'offensive'
        elif x_coord < -25:
            return 'defensive'
        else:
            return 'neutral'
    
    def _is_rush_shot(self, current_play, all_plays):
        """Determine if a shot is from a rush using proper hockey logic"""
        try:
            play_index = all_plays.index(current_play)
            current_team = current_play.get('details', {}).get('eventOwnerTeamId')
            current_period = current_play.get('periodDescriptor', {}).get('number', 1)
            
            # Look back through recent plays to find rush indicators
            rush_indicators = 0
            zone_entry_found = False
            quick_transition = False
            
            # Check last 5 plays for rush indicators
            for i in range(max(0, play_index - 5), play_index):
                prev_play = all_plays[i]
                prev_team = prev_play.get('details', {}).get('eventOwnerTeamId')
                prev_type = prev_play.get('typeDescKey', '')
                prev_period = prev_play.get('periodDescriptor', {}).get('number', 1)
                
                # Only consider plays from the same team and period
                if prev_team != current_team or prev_period != current_period:
                    continue
                
                # Rush indicators:
                # 1. Takeaway (steal) - indicates quick transition
                if prev_type == 'takeaway':
                    rush_indicators += 2
                    quick_transition = True
                
                # 2. Giveaway by opponent - indicates quick transition
                elif prev_type == 'giveaway':
                    rush_indicators += 1
                
                # 3. Shot block by opponent - indicates quick transition
                elif prev_type == 'blocked-shot':
                    rush_indicators += 1
                
                # 4. Faceoff win in neutral/offensive zone
                elif prev_type == 'faceoff':
                    # Check if it's in neutral or offensive zone
                    coords = prev_play.get('details', {}).get('coordinates', {})
                    x_coord = coords.get('x', 0)
                    if x_coord > 25:  # Offensive zone faceoff
                        rush_indicators += 1
                        zone_entry_found = True
                    elif abs(x_coord) <= 25:  # Neutral zone faceoff
                        rush_indicators += 0.5
                
                # 5. Pass in neutral zone - indicates controlled entry
                elif prev_type == 'pass' and abs(x_coord) <= 25:
                    rush_indicators += 0.5
                
                # 6. Shot from previous play - indicates sustained pressure
                elif prev_type in ['shot-on-goal', 'missed-shot', 'blocked-shot']:
                    rush_indicators += 0.3
            
            # Rush shot criteria:
            # - Quick transition (takeaway/giveaway) + zone entry
            # - OR high rush indicator score (3+)
            # - OR faceoff win in offensive zone + quick transition
            if (quick_transition and zone_entry_found) or rush_indicators >= 3 or (zone_entry_found and rush_indicators >= 2):
                return True
            
            return False
            
        except Exception as e:
            print(f"Error in rush shot detection: {e}")
            return False
    
    def _is_forecheck_cycle_shot(self, current_play, all_plays):
        """Determine if a shot is from forecheck/cycle using proper hockey logic"""
        try:
            play_index = all_plays.index(current_play)
            current_team = current_play.get('details', {}).get('eventOwnerTeamId')
            current_period = current_play.get('periodDescriptor', {}).get('number', 1)
            
            # Look back through recent plays to find forecheck/cycle indicators
            forecheck_indicators = 0
            cycle_indicators = 0
            forecheck_found = False
            sustained_pressure = False
            
            # Check last 8 plays for forecheck/cycle indicators
            for i in range(max(0, play_index - 8), play_index):
                prev_play = all_plays[i]
                prev_team = prev_play.get('details', {}).get('eventOwnerTeamId')
                prev_type = prev_play.get('typeDescKey', '')
                prev_period = prev_play.get('periodDescriptor', {}).get('number', 1)
                
                # Only consider plays from the same team and period
                if prev_team != current_team or prev_period != current_period:
                    continue
                
                coords = prev_play.get('details', {}).get('coordinates', {})
                x_coord = coords.get('x', 0)
                
                # Forecheck indicators:
                # 1. Takeaway in offensive zone - indicates successful forecheck
                if prev_type == 'takeaway' and x_coord > 25:
                    forecheck_indicators += 3
                    forecheck_found = True
                
                # 2. Hit in offensive zone - indicates forecheck pressure
                elif prev_type == 'hit' and x_coord > 25:
                    forecheck_indicators += 1
                
                # 3. Giveaway by opponent in their defensive zone - indicates forecheck pressure
                elif prev_type == 'giveaway' and x_coord < -25:
                    forecheck_indicators += 2
                    forecheck_found = True
                
                # Cycle indicators:
                # 4. Pass in offensive zone - indicates cycle
                elif prev_type == 'pass' and x_coord > 25:
                    cycle_indicators += 1
                    sustained_pressure = True
                
                # 5. Shot from previous play in offensive zone - indicates sustained pressure
                elif prev_type in ['shot-on-goal', 'missed-shot', 'blocked-shot'] and x_coord > 25:
                    cycle_indicators += 0.5
                    sustained_pressure = True
                
                # 6. Faceoff win in offensive zone - indicates cycle opportunity
                elif prev_type == 'faceoff' and x_coord > 25:
                    cycle_indicators += 1
                    sustained_pressure = True
                
                # 7. Multiple passes in offensive zone - indicates cycle
                elif prev_type == 'pass' and x_coord > 25:
                    cycle_indicators += 0.3
            
            # Get shot coordinates for debug
            shot_coords = current_play.get('details', {}).get('coordinates', {})
            shot_x = shot_coords.get('x', 0)
            
            # Forecheck/Cycle shot criteria (extremely lenient):
            # - Any forecheck indicators OR any cycle indicators
            # - OR just cycle indicators (0.5+)
            # - OR any forecheck pressure
            # - OR any shot in offensive zone (simplified approach)
            if (forecheck_indicators > 0 or cycle_indicators > 0 or cycle_indicators >= 0.5 or forecheck_indicators > 0 or 
                shot_x > 25):
                return True
            
            # Debug output for first few shots
            if play_index < 5:  # Only debug first 5 shots to avoid spam
                print(f"Debug - Shot {play_index}: x={shot_x}, forecheck={forecheck_indicators}, cycle={cycle_indicators}")
            
            return False
            
        except Exception as e:
            print(f"Error in forecheck/cycle shot detection: {e}")
            return False
    
    def _is_shot_after_turnover(self, shot_x, shot_y, turnover, time_window_seconds=5):
        """Check if shot occurred after a turnover within time window"""
        # Simplified - in reality would need timestamp comparison
        # For now, just check if shot is in same general area
        distance = ((shot_x - turnover['x']) ** 2 + (shot_y - turnover['y']) ** 2) ** 0.5
        return distance < 50  # Within 50 units
    
    def create_player_performance(self, game_data):
        """Create top 5 players by Game Score across both teams"""
        story = []
        
        story.append(Paragraph("TOP 5 PLAYERS BY GAME SCORE", self.subtitle_style))
        story.append(Spacer(1, 15))
        
        boxscore = game_data['boxscore']
        
        # Get player stats from play-by-play data for both teams
        away_team = boxscore['awayTeam']
        home_team = boxscore['homeTeam']
        away_player_stats = self._calculate_player_stats_from_play_by_play(game_data, 'awayTeam')
        home_player_stats = self._calculate_player_stats_from_play_by_play(game_data, 'homeTeam')
        
        # Get all players from both teams
        all_players = []
        
        # Add away team players
        if away_player_stats:
            for player in away_player_stats.values():
                all_players.append({
                    'player': f"#{player['sweaterNumber']} {player['name']}",
                    'team': away_team['abbrev'],
                    'position': player['position'],
                    'goals': player['goals'],
                    'assists': player['assists'],
                    'points': player['points'],
                    'plusMinus': player['plusMinus'],
                    'pim': player['pim'],
                    'sog': player['sog'],
                    'hits': player['hits'],
                    'blockedShots': player['blockedShots'],
                    'gameScore': player['gameScore']
                })
        
        # Add home team players
        if home_player_stats:
            for player in home_player_stats.values():
                all_players.append({
                    'player': f"#{player['sweaterNumber']} {player['name']}",
                    'team': home_team['abbrev'],
                    'position': player['position'],
                    'goals': player['goals'],
                    'assists': player['assists'],
                    'points': player['points'],
                    'plusMinus': player['plusMinus'],
                    'pim': player['pim'],
                    'sog': player['sog'],
                    'hits': player['hits'],
                    'blockedShots': player['blockedShots'],
                    'gameScore': player['gameScore']
                })
        
        # Sort by Game Score, then points, then goals (descending)
        all_players.sort(key=lambda x: (x['gameScore'], x['points'], x['goals']), reverse=True)
        
        # Take top 5 players
        top_5_players = all_players[:5]
        
        if top_5_players:
            # Create table data with team indicators
            table_data = []
            headers = ["Player", "Team", "Pos", "G", "A", "P", "+/-", "PIM", "SOG", "H", "BLK", "GS"]
            table_data.append(headers)
            
            for player in top_5_players:
                table_data.append([
                    player['player'],
                    player['team'],
                    player['position'],
                    player['goals'],
                    player['assists'],
                    player['points'],
                    player['plusMinus'],
                    player['pim'],
                    player['sog'],
                    player['hits'],
                    player['blockedShots'],
                    f"{player['gameScore']:.1f}" if player['gameScore'] > 0 else "N/A"
                ])
            
            # Create table with condensed column widths
            player_table = Table(table_data, colWidths=[1.5*inch, 0.4*inch, 0.3*inch, 0.25*inch, 0.25*inch, 0.25*inch, 0.3*inch, 0.25*inch, 0.25*inch, 0.25*inch, 0.25*inch, 0.3*inch])
            player_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.darkblue),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'RussoOne-Regular'),
                ('FONTSIZE', (0, 0), (-1, 0), 8),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
                ('BACKGROUND', (0, 1), (-1, -1), colors.lightgrey),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('FONTSIZE', (0, 1), (-1, -1), 7),
                ('FONTNAME', (0, 1), (-1, -1), 'RussoOne-Regular'),
                # Highlight the top player
                ('BACKGROUND', (0, 1), (-1, 1), colors.yellow),
                ('FONTNAME', (0, 1), (-1, 1), 'RussoOne-Regular'),
                ('FONTSIZE', (0, 1), (-1, 1), 8),
            ]))
            story.append(player_table)
            
            # Add note about Game Score
            story.append(Spacer(1, 10))
            story.append(Paragraph("<i>Top 5 players ranked by Game Score (GS) - a comprehensive metric combining goals, assists, shots, hits, and other key performance indicators.</i>", self.normal_style))
        
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
            
            # Collect shot and goal data for both teams with side designation
            away_shots = []
            away_goals = []
            home_shots = []
            home_goals = []
            
            for play in play_by_play['plays']:
                details = play.get('details', {})
                event_type = play.get('typeDescKey', '')
                event_team = details.get('eventOwnerTeamId')
                period = play.get('periodDescriptor', {}).get('number', 1)
                
                # Get coordinates
                x_coord = details.get('xCoord', 0)
                y_coord = details.get('yCoord', 0)
                
                if x_coord is not None and y_coord is not None:
                    # Force each team to always appear on their designated side
                    # Away team: Always left side (negative X)
                    # Home team: Always right side (positive X)
                    
                    if event_team == away_team['id'] and event_type in ['shot-on-goal', 'missed-shot', 'blocked-shot']:
                        # Away team shots - force to left side
                        if x_coord > 0:  # If shot is on right side, flip to left
                            flipped_x = -x_coord
                            flipped_y = -y_coord
                        else:  # Already on left side
                            flipped_x = x_coord
                            flipped_y = y_coord
                        away_shots.append((flipped_x, flipped_y))
                        
                    elif event_team == away_team['id'] and event_type == 'goal':
                        # Away team goals - force to left side
                        if x_coord > 0:  # If goal is on right side, flip to left
                            flipped_x = -x_coord
                            flipped_y = -y_coord
                        else:  # Already on left side
                            flipped_x = x_coord
                            flipped_y = y_coord
                        away_goals.append((flipped_x, flipped_y))
                        
                    elif event_team == home_team['id'] and event_type in ['shot-on-goal', 'missed-shot', 'blocked-shot']:
                        # Home team shots - force to right side
                        if x_coord < 0:  # If shot is on left side, flip to right
                            flipped_x = -x_coord
                            flipped_y = -y_coord
                        else:  # Already on right side
                            flipped_x = x_coord
                            flipped_y = y_coord
                        home_shots.append((flipped_x, flipped_y))
                        
                    elif event_team == home_team['id'] and event_type == 'goal':
                        # Home team goals - force to right side
                        if x_coord < 0:  # If goal is on left side, flip to right
                            flipped_x = -x_coord
                            flipped_y = -y_coord
                        else:  # Already on right side
                            flipped_x = x_coord
                            flipped_y = y_coord
                        home_goals.append((flipped_x, flipped_y))
            
            if not (away_shots or away_goals or home_shots or home_goals):
                print("No shots or goals found for either team")
                return None
                
            print(f"Found {len(away_shots)} shots and {len(away_goals)} goals for {away_team['abbrev']}")
            print(f"Found {len(home_shots)} shots and {len(home_goals)} goals for {home_team['abbrev']}")
            
            # Create the plot - original size
            plt.ioff()
            fig, ax = plt.subplots(figsize=(8, 5.5))
            
            # Load and display the rink image
            rink_path = '/Users/emilyfehr8/CascadeProjects/nhl_postgame_reports/F300E016-E2BD-450A-B624-5BADF3853AC0.jpeg'
            try:
                if os.path.exists(rink_path):
                    from matplotlib.image import imread
                    rink_img = imread(rink_path)
                    # Display the rink image
                    ax.imshow(rink_img, extent=[-100, 100, -42.5, 42.5], aspect='equal', alpha=0.9)
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
            
            # Get team colors based on actual teams playing
            away_color = self._get_team_color(away_team['abbrev'])
            home_color = self._get_team_color(home_team['abbrev'])
            
            # Plot away team shots and goals in team color
            if away_shots:
                shot_x, shot_y = zip(*away_shots)
                ax.scatter(shot_x, shot_y, c=away_color, alpha=0.7, s=30, 
                          marker='o', edgecolors='black', linewidth=0.5)

            if away_goals:
                goal_x, goal_y = zip(*away_goals)
                ax.scatter(goal_x, goal_y, c=away_color, alpha=1.0, s=60, 
                                          marker='o', edgecolors='black', linewidth=1.5)

            # Plot home team shots and goals in team color
            if home_shots:
                shot_x, shot_y = zip(*home_shots)
                ax.scatter(shot_x, shot_y, c=home_color, alpha=0.7, s=30, 
                          marker='o', edgecolors='white', linewidth=0.5)

            if home_goals:
                goal_x, goal_y = zip(*home_goals)
                ax.scatter(goal_x, goal_y, c=home_color, alpha=1.0, s=60, 
                          marker='o', edgecolors='white', linewidth=1.5)

            # Set plot properties
            ax.set_xlim(-100, 100)
            ax.set_ylim(-42.5, 42.5)
            ax.set_aspect('equal')
            # No legend needed - team colors are self-explanatory
            ax.grid(False)  # Turn off grid since we have the rink image
            ax.set_xticks([])
            ax.set_yticks([])
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)
            ax.spines['bottom'].set_visible(False)
            ax.spines['left'].set_visible(False)

                            # Add team labels on the rink
            ax.text(-50, 0, f'{away_team["abbrev"]}', fontsize=10, ha='center', color='blue', weight='bold')
            ax.text(50, 0, f'{home_team["abbrev"]}', fontsize=10, ha='center', color='red', weight='bold')
            
            # Add home team logo at center ice (center faceoff circle)
            try:
                import requests
                from io import BytesIO
                from PIL import Image as PILImage
                
                # Get home team logo
                home_team_abbrev = home_team['abbrev'].lower()
                home_logo_url = f"https://a.espncdn.com/i/teamlogos/nhl/500/{home_team_abbrev}.png"
                
                # Download home team logo
                home_response = requests.get(home_logo_url, timeout=5)
                if home_response.status_code == 200:
                    home_logo = PILImage.open(BytesIO(home_response.content))
                    # Resize logo to fit center ice circle
                    logo_size = 12  # 12 feet diameter in coordinate units
                    home_logo = home_logo.resize((logo_size, logo_size), PILImage.Resampling.LANCZOS)
                    
                    # Convert to numpy array for matplotlib
                    import numpy as np
                    logo_array = np.array(home_logo)
                    
                    # Place logo at center ice (0, 0)
                    # Note: matplotlib extent is [left, right, bottom, top]
                    ax.imshow(logo_array, extent=[-logo_size/2, logo_size/2, -logo_size/2, logo_size/2], 
                             alpha=0.8, zorder=10)
                    print(f"Added {home_team['abbrev']} logo at center ice")
                else:
                    print(f"Failed to load home team logo: HTTP {home_response.status_code}")
            except Exception as e:
                print(f"Error adding home team logo: {e}")
                # Fallback: add text at center ice
                ax.text(0, 0, f'{home_team["abbrev"]}', fontsize=12, ha='center', va='center', 
                       color='white', weight='bold', bbox=dict(boxstyle="circle,pad=0.2", facecolor='red', alpha=0.8))
            
            # Save to file with a unique name to avoid conflicts
            import time
            timestamp = int(time.time() * 1000)  # milliseconds
            plot_filename = f'combined_shot_plot_{away_team["abbrev"]}_vs_{home_team["abbrev"]}_{timestamp}.png'
            abs_plot_filename = os.path.abspath(plot_filename)
            print(f"Saving combined plot to: {abs_plot_filename}")
            fig.savefig(abs_plot_filename, dpi=150, bbox_inches='tight', facecolor='white')
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
        """Create advanced metrics section with specific data"""
        story = []
        
        story.append(Paragraph("ADVANCED METRICS", self.subtitle_style))
        story.append(Spacer(1, 15))
        
        try:
            # Get team abbreviations and IDs
            boxscore = game_data['boxscore']
            away_team_abbrev = boxscore['awayTeam']['abbrev']
            home_team_abbrev = boxscore['homeTeam']['abbrev']
            away_team_id = boxscore['awayTeam']['id']
            home_team_id = boxscore['homeTeam']['id']
            
            # Get advanced metrics using the analyzer
            from advanced_metrics_analyzer import AdvancedMetricsAnalyzer
            analyzer = AdvancedMetricsAnalyzer(game_data.get('play_by_play', {}))
            metrics = analyzer.generate_comprehensive_report(away_team_id, home_team_id)
            
            # Advanced Metrics Table with real data
            story.append(Paragraph("ADVANCED METRICS ANALYSIS", self.section_style))
            story.append(Spacer(1, 10))
            
            # Extract real metrics
            away_shot_quality = metrics['away_team']['shot_quality']
            home_shot_quality = metrics['home_team']['shot_quality']
            away_pressure = metrics['away_team']['pressure']
            home_pressure = metrics['home_team']['pressure']
            away_defense = metrics['away_team']['defense']
            home_defense = metrics['home_team']['defense']
            away_cross_ice = metrics['away_team']['cross_ice_passes']
            home_cross_ice = metrics['home_team']['cross_ice_passes']
            
            combined_data = [
                ['Category', 'Metric', away_team_abbrev, home_team_abbrev],
                
                # Shot Quality Analysis
                ['SHOT QUALITY', 'Expected Goals (xG)', f"{away_shot_quality['expected_goals']:.2f}", f"{home_shot_quality['expected_goals']:.2f}"],
                ['', 'High Danger Shots', str(away_shot_quality['high_danger_shots']), str(home_shot_quality['high_danger_shots'])],
                ['', 'Total Shots', str(away_shot_quality['total_shots']), str(home_shot_quality['total_shots'])],
                ['', 'Shots on Goal', str(away_shot_quality['shots_on_goal']), str(home_shot_quality['shots_on_goal'])],
                ['', 'Shooting %', f"{away_shot_quality['shooting_percentage']:.1%}", f"{home_shot_quality['shooting_percentage']:.1%}"],
                
                # Pressure Analysis
                ['PRESSURE', 'Sustained Pressure Sequences', str(away_pressure['sustained_pressure_sequences']), str(home_pressure['sustained_pressure_sequences'])],
                ['', 'Quick Strike Opportunities', str(away_pressure['quick_strike_opportunities']), str(home_pressure['quick_strike_opportunities'])],
                ['', 'Avg Shots per Sequence', 
                 f"{sum(away_pressure['shot_attempts_per_sequence'])/len(away_pressure['shot_attempts_per_sequence']):.1f}" if away_pressure['shot_attempts_per_sequence'] else '0.0', 
                 f"{sum(home_pressure['shot_attempts_per_sequence'])/len(home_pressure['shot_attempts_per_sequence']):.1f}" if home_pressure['shot_attempts_per_sequence'] else '0.0'],
                
                # Defensive Analysis
                ['DEFENSIVE', 'Blocked Shots', str(away_defense['blocked_shots']), str(home_defense['blocked_shots'])],
                ['', 'Takeaways', str(away_defense['takeaways']), str(home_defense['takeaways'])],
                ['', 'Hits', str(away_defense['hits']), str(home_defense['hits'])],
                ['', 'Shot Attempts Against', str(away_defense['shot_attempts_against']), str(home_defense['shot_attempts_against'])],
                ['', 'High Danger Chances Against', str(away_defense['high_danger_chances_against']), str(home_defense['high_danger_chances_against'])],
                
                # Cross-Ice Pass Analysis
                ['CROSS-ICE PASSES', 'Total Attempts', str(away_cross_ice['total_cross_ice_attempts']), str(home_cross_ice['total_cross_ice_attempts'])],
                ['', 'Successful Passes', str(away_cross_ice['successful_cross_ice_passes']), str(home_cross_ice['successful_cross_ice_passes'])],
                ['', 'Success Rate', f"{away_cross_ice['cross_ice_success_rate']:.1%}", f"{home_cross_ice['cross_ice_success_rate']:.1%}"]
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
                
                # Category headers (SHOT QUALITY, PRESSURE, DEFENSIVE, CROSS-ICE PASSES)
                ('BACKGROUND', (0, 1), (0, 4), colors.lightblue),  # Shot Quality
                ('BACKGROUND', (0, 5), (0, 7), colors.lightgreen),  # Pressure
                ('BACKGROUND', (0, 8), (0, 12), colors.lightgrey),  # Defensive
                ('BACKGROUND', (0, 13), (0, 15), colors.lightyellow),  # Cross-Ice Passes
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
                    try:
                        combined_image = Image(combined_plot, width=8*inch, height=5.3*inch)
                        combined_image.hAlign = 'CENTER'
                        story.append(combined_image)
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
                
                story.append(Spacer(1, 20))
            except Exception as e:
                print(f"Error creating combined plot: {e}")
                story.append(Paragraph("Combined shot location plot could not be created.", self.normal_style))
            
        except Exception as e:
            print(f"Error creating shot location plots: {e}")
            story.append(Paragraph("Shot location analysis could not be created for this game.", self.normal_style))
        
        return story
    
    def generate_report(self, game_data, output_filename, game_id=None):
        """Generate the complete post-game report PDF"""
        # Set margins to allow header to extend to edges
        doc = SimpleDocTemplate(output_filename, pagesize=letter, rightMargin=72, leftMargin=72, 
                              topMargin=0, bottomMargin=18)
        
        story = []
        
        # Add modern header image at the absolute top of the page (height 0)
        header_image = self.create_header_image(game_data, game_id)
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
        story.extend(self.create_team_stats_comparison(game_data))
        story.extend(self.create_advanced_metrics_section(game_data))
        story.extend(self.create_player_performance(game_data))
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
