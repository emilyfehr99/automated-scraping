"""
Advanced NHL Metrics Analyzer
Creates custom hockey analytics from play-by-play data
"""

import json
from collections import defaultdict
from typing import Dict, List, Tuple, Optional

class AdvancedMetricsAnalyzer:
    def __init__(self, play_by_play_data: dict):
        self.plays = play_by_play_data.get('plays', [])
        self.roster_map = self._create_roster_map(play_by_play_data)
        
    def _create_roster_map(self, play_by_play_data: dict) -> dict:
        """Create a mapping of player IDs to player info"""
        roster_map = {}
        if 'rosterSpots' in play_by_play_data:
            for player in play_by_play_data['rosterSpots']:
                player_id = player['playerId']
                roster_map[player_id] = {
                    'firstName': player['firstName']['default'],
                    'lastName': player['lastName']['default'],
                    'sweaterNumber': player['sweaterNumber'],
                    'positionCode': player['positionCode'],
                    'teamId': player['teamId']
                }
        return roster_map
    
    def get_available_metrics(self) -> dict:
        """Get all available metrics from the play-by-play data"""
        metrics = {
            'event_types': defaultdict(int),
            'spatial_data': set(),
            'player_actions': defaultdict(int),
            'zone_activities': defaultdict(int),
            'shot_types': set(),
            'penalty_types': set()
        }
        
        for play in self.plays:
            event_type = play.get('typeDescKey', '')
            details = play.get('details', {})
            
            # Count event types
            metrics['event_types'][event_type] += 1
            
            # Collect spatial data
            if 'xCoord' in details and 'yCoord' in details:
                metrics['spatial_data'].add('coordinates')
            if 'zoneCode' in details:
                metrics['zone_activities'][details['zoneCode']] += 1
                
            # Collect player actions
            for key in details.keys():
                if 'PlayerId' in key:
                    metrics['player_actions'][key] += 1
                    
            # Collect shot types
            if 'shotType' in details:
                metrics['shot_types'].add(details['shotType'])
                
            # Collect penalty types
            if 'descKey' in details and event_type == 'penalty':
                metrics['penalty_types'].add(details['descKey'])
        
        return metrics
    
    
    def calculate_shot_quality_metrics(self, team_id: int) -> dict:
        """Calculate advanced shot quality metrics"""
        shot_quality = {
            'total_shots': 0,
            'shots_on_goal': 0,
            'missed_shots': 0,
            'blocked_shots': 0,
            'shot_types': defaultdict(int),
            'shot_locations': defaultdict(int),
            'high_danger_shots': 0,
            'shooting_percentage': 0,
            'expected_goals': 0
        }
        
        for play in self.plays:
            details = play.get('details', {})
            event_type = play.get('typeDescKey', '')
            event_team = details.get('eventOwnerTeamId')
            
            if event_team != team_id:
                continue
                
            if event_type in ['shot-on-goal', 'missed-shot', 'blocked-shot']:
                shot_quality['total_shots'] += 1
                
                if event_type == 'shot-on-goal':
                    shot_quality['shots_on_goal'] += 1
                elif event_type == 'missed-shot':
                    shot_quality['missed_shots'] += 1
                elif event_type == 'blocked-shot':
                    shot_quality['blocked_shots'] += 1
                
                # Shot type analysis
                shot_type = details.get('shotType', 'unknown')
                shot_quality['shot_types'][shot_type] += 1
                
                # Location analysis
                x_coord = details.get('xCoord', 0)
                y_coord = details.get('yCoord', 0)
                zone = details.get('zoneCode', '')
                
                # High danger area (close to net, in front)
                if zone == 'O' and x_coord > 50 and abs(y_coord) < 20:
                    shot_quality['high_danger_shots'] += 1
                
                # Zone analysis
                shot_quality['shot_locations'][zone] += 1
        
        # Calculate shooting percentage
        if shot_quality['total_shots'] > 0:
            shot_quality['shooting_percentage'] = shot_quality['shots_on_goal'] / shot_quality['total_shots']
        
        return shot_quality
    
    def calculate_pressure_metrics(self, team_id: int) -> dict:
        """Calculate offensive pressure metrics"""
        pressure = {
            'sustained_pressure_sequences': 0,
            'quick_strike_opportunities': 0,
            'zone_time': defaultdict(int),
            'shot_attempts_per_sequence': [],
            'pressure_players': defaultdict(int)
        }
        
        current_sequence = []
        sequence_start_time = None
        
        for play in self.plays:
            details = play.get('details', {})
            event_type = play.get('typeDescKey', '')
            event_team = details.get('eventOwnerTeamId')
            time_in_period = play.get('timeInPeriod', '00:00')
            
            # Convert time to seconds for analysis
            try:
                minutes, seconds = time_in_period.split(':')
                time_seconds = int(minutes) * 60 + int(seconds)
            except:
                time_seconds = 0
            
            if event_team == team_id:
                if not current_sequence:
                    sequence_start_time = time_seconds
                    current_sequence = []
                
                current_sequence.append({
                    'event_type': event_type,
                    'time': time_seconds,
                    'zone': details.get('zoneCode', ''),
                    'player_id': details.get('playerId') or details.get('shootingPlayerId')
                })
                
                # Track zone time
                zone = details.get('zoneCode', '')
                if zone:
                    pressure['zone_time'][zone] += 1
                    
            else:
                # End of possession sequence
                if current_sequence and sequence_start_time:
                    sequence_duration = time_seconds - sequence_start_time
                    shot_attempts = len([e for e in current_sequence if 'shot' in e['event_type']])
                    
                    pressure['shot_attempts_per_sequence'].append(shot_attempts)
                    
                    if sequence_duration > 30:  # Sustained pressure
                        pressure['sustained_pressure_sequences'] += 1
                    elif shot_attempts > 0:  # Quick strike
                        pressure['quick_strike_opportunities'] += 1
                    
                    # Track players involved in pressure
                    for event in current_sequence:
                        if event['player_id']:
                            pressure['pressure_players'][event['player_id']] += 1
                
                current_sequence = []
                sequence_start_time = None
        
        return pressure
    
    def calculate_defensive_metrics(self, team_id: int) -> dict:
        """Calculate defensive metrics"""
        defense = {
            'blocked_shots': 0,
            'takeaways': 0,
            'hits': 0,
            'defensive_zone_clears': 0,
            'penalty_kill_efficiency': 0,
            'shot_attempts_against': 0,
            'high_danger_chances_against': 0,
            'defensive_players': defaultdict(int)
        }
        
        penalty_situations = []
        current_penalty = None
        
        for play in self.plays:
            details = play.get('details', {})
            event_type = play.get('typeDescKey', '')
            event_team = details.get('eventOwnerTeamId')
            zone = details.get('zoneCode', '')
            
            # Track penalty situations
            if event_type == 'penalty':
                if event_team != team_id:  # Opponent penalty
                    current_penalty = {
                        'start_time': play.get('timeInPeriod', '00:00'),
                        'duration': details.get('duration', 0)
                    }
                else:  # Our penalty
                    penalty_situations.append({
                        'start_time': play.get('timeInPeriod', '00:00'),
                        'duration': details.get('duration', 0)
                    })
            
            # Count defensive actions
            if event_team == team_id:
                if event_type == 'blocked-shot':
                    defense['blocked_shots'] += 1
                    player_id = details.get('blockingPlayerId')
                    if player_id:
                        defense['defensive_players'][player_id] += 1
                        
                elif event_type == 'takeaway':
                    defense['takeaways'] += 1
                    player_id = details.get('playerId')
                    if player_id:
                        defense['defensive_players'][player_id] += 1
                        
                elif event_type == 'hit':
                    defense['hits'] += 1
                    player_id = details.get('hittingPlayerId')
                    if player_id:
                        defense['defensive_players'][player_id] += 1
                        
                elif event_type == 'giveaway' and zone == 'D':
                    defense['defensive_zone_clears'] += 1
            
            # Track shots against
            elif event_type in ['shot-on-goal', 'missed-shot']:
                defense['shot_attempts_against'] += 1
                
                # High danger chances
                x_coord = details.get('xCoord', 0)
                if zone == 'O' and x_coord > 50 and abs(details.get('yCoord', 0)) < 20:
                    defense['high_danger_chances_against'] += 1
        
        return defense
    
    def generate_comprehensive_report(self, away_team_id: int, home_team_id: int) -> dict:
        """Generate a comprehensive advanced metrics report"""
        report = {
            'away_team': {
                'team_id': away_team_id,
                'shot_quality': self.calculate_shot_quality_metrics(away_team_id),
                'pressure': self.calculate_pressure_metrics(away_team_id),
                'defense': self.calculate_defensive_metrics(away_team_id)
            },
            'home_team': {
                'team_id': home_team_id,
                'shot_quality': self.calculate_shot_quality_metrics(home_team_id),
                'pressure': self.calculate_pressure_metrics(home_team_id),
                'defense': self.calculate_defensive_metrics(home_team_id)
            },
            'available_metrics': self.get_available_metrics()
        }
        
        return report

def analyze_game_metrics(game_id: str) -> dict:
    """Analyze advanced metrics for a specific game"""
    import requests
    
    # Fetch play-by-play data
    url = f"https://api-web.nhle.com/v1/gamecenter/{game_id}/play-by-play"
    response = requests.get(url)
    
    if response.status_code != 200:
        return {"error": "Could not fetch game data"}
    
    play_by_play_data = response.json()
    
    # Get team IDs from boxscore
    boxscore_url = f"https://api-web.nhle.com/v1/gamecenter/{game_id}/boxscore"
    boxscore_response = requests.get(boxscore_url)
    
    if boxscore_response.status_code != 200:
        return {"error": "Could not fetch boxscore data"}
    
    boxscore_data = boxscore_response.json()
    away_team_id = boxscore_data['awayTeam']['id']
    home_team_id = boxscore_data['homeTeam']['id']
    
    # Create analyzer and generate report
    analyzer = AdvancedMetricsAnalyzer(play_by_play_data)
    return analyzer.generate_comprehensive_report(away_team_id, home_team_id)

if __name__ == "__main__":
    # Test with current game
    game_id = "2024020088"
    metrics = analyze_game_metrics(game_id)
    
    print("🏒 ADVANCED NHL METRICS ANALYSIS 🏒")
    print("=" * 50)
    
    if "error" in metrics:
        print(f"Error: {metrics['error']}")
    else:
        print(f"Game ID: {game_id}")
        print(f"Available Event Types: {list(metrics['available_metrics']['event_types'].keys())}")
        print(f"Shot Types: {list(metrics['available_metrics']['shot_types'])}")
        print(f"Zone Activities: {dict(metrics['available_metrics']['zone_activities'])}")
        
        print("\n📊 CUSTOM METRICS SUMMARY:")
        print(f"Away Team High Danger Shots: {metrics['away_team']['shot_quality']['high_danger_shots']}")
        print(f"Away Team Sustained Pressure: {metrics['away_team']['pressure']['sustained_pressure_sequences']}")
        print(f"Away Team Blocked Shots: {metrics['away_team']['defense']['blocked_shots']}")
        
        print(f"\nHome Team High Danger Shots: {metrics['home_team']['shot_quality']['high_danger_shots']}")
        print(f"Home Team Sustained Pressure: {metrics['home_team']['pressure']['sustained_pressure_sequences']}")
        print(f"Home Team Blocked Shots: {metrics['home_team']['defense']['blocked_shots']}")
