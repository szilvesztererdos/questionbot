import os
import time
import re
from datetime import date, datetime
from slackclient import SlackClient

# constants
BOT_ID = os.environ.get("BOT_ID")
BOT_NAME = 'questionbot'
START_COMMAND = 'start'
STOP_COMMAND = 'stop'
NUMBERS = ('first', 'second', 'third')
DAILY_START_HOURS = 8

MSG_WELCOME = ('Hi! I am questionbot and I invite you to play a little game which furthermore will '
               'help you maintain your programming knowledge, you can get to know your classmates '
               'better and it\'s FUN :)\n'
               'You will be asked to set up three statements and corresponding true/false answers and '
               'after that you will be paired with one of your classmates who is also playing this '
               'game. Each of you will make a guess and after the end of that round you will be paired '
               'with another classmate until there are no one left or the time is up.')
MSG_SETUP = ('Please give me three statements and corresponding true/false answers in connection with this '
             'week\'s material! You can type "cancel" anytime to opt-out of the game for that week.')
MSG_QUESTION = 'What\'s your {number} statement?'
MSG_QUESTION_DONE = 'Thanks, I set up your {number} statement as "{question}".'
MSG_ANSWER = 'What\'s the answer for the {number} statement? (true/false)'
MSG_ANSWER_DONE = 'Thanks, I set up the answer for the {number} statement as "{answer}".'
MSG_ANSWER_REPEAT = ('Sorry, I didn\'t get that. Please, tell me again the answer for the {number} statement!'
                     '(true/false)')
MSG_SETUP_DONE = ('Okay, you\'re set up. Please wait until other players join the game, I will pair you up with them. '
                  'Stay tuned! ;)')
MSG_ADMIN_UNKNOWN_COMMAND = 'Sorry, I didn\'t recognize any command. Use "start [#channel]" to start a game!'
MSG_ADMIN_STARTING_GAME_CHANNEL = 'Starting game in channel #{channel}.'
MSG_ADMIN_STARTING_GAME_TEAM = 'Starting game for the whole team.'
MSG_ADMIN_CONFIRM_START_TEAM = 'Are you sure you want to start a game for the whole team? (yes/no)'
MSG_ADMIN_CONFIRM_START_CHANNEL = 'Are you sure you want to start a game in the channel #{channel}? (yes/no)'
MSG_ADMIN_CONFIRM_START_CANCEL = 'Game start cancelled.'
MSG_ADMIN_STOPPING_GAME = 'Stopping game.'
MSG_ADMIN_CONFIRM_STOP = 'Are you sure you want to end the game? (yes/no)'
MSG_ADMIN_CONFIRM_STOP_CANCEL = 'Game stop cancelled.'
MSG_USER_UNKNOWN_COMMAND = ('Currently there isn\'t any game ongoing. Please wait for the next round or '
                            'contact an admin!')
MSG_NOT_YOUR_TURN = 'It\'s not your turn now. Please, wait until your opponent finishes!'
MSG_SAY_IN_MPIM = 'Please, asnwer the question in the group direct message with your opponent!'
MSG_ROUND_START = ('Hey fellas! You are chosen to test each other\'s knowledge today. Each of you have to answer '
                   'the other\'s questions and each correct answer counts as one point.')
MSG_ROUND_NEXT_USER = '@{user_name}: It\'s your turn, please answer the following questions.'
MSG_ROUND_QUESTION = '@{user_name}: The {number} question is: {question}\nIs it true or false?'
MSG_ROUND_ANSWER_REPEAT = '@{user_name}: Sorry, I didn\'t get that. Please repeat your answer!'
MSG_ROUND_ANSWER_CORRECT = '@{user_name}: Yes, you\'re right! 1 point for you :)'
MSG_ROUND_ANSWER_INCORRECT = '@{user_name}: Sorry, you\'re wrong. Maybe next time!'
MSG_ROUND_END = ('Okay, that\'s it. Thanks guys for the questions and the answers. We\'ll meet tomorrow '
                 '(if there are any players left and the game is still on).')
MSG_ROUND_POINTS = 'Huh, it was great! You have {points} points at the end of the round.'
MSG_END_GAME = ('Dear @channel! The question game has ended. Players with the top points are:\n'
                '1. @{player_1}: {points_1} points\n'
                '2. @{player_2}: {points_2} points\n'
                '3. @{player_3}: {points_3} points\n')

# TODO: switch to nosql (redis?)
# globals
slack_client = SlackClient(os.environ.get('SLACK_BOT_TOKEN'))
storage = {
    'status': 'wait',
    'players': {},
    'channel': None
}


def slack_api(method, **kwargs):
    api_call = slack_client.api_call(method, **kwargs)
    if api_call.get('ok'):
        return api_call
    else:
        raise ValueError('Connection error!', api_call.get('error'), api_call.get('args'))


def log(scope, message):
    print('{}: {}'.format(scope, message))


def is_admin(user_id):
    api_call = slack_api('users.info', user=user_id)
    user = api_call.get('user')
    if 'is_admin' in user and user.get('is_admin') is True:
        return True
    else:
        return False


def send_im(user_id, message):
    api_call = slack_api('im.open', user=user_id)
    channel_id = api_call.get('channel').get('id')
    slack_api('chat.postMessage', channel=channel_id, text=message, username=BOT_NAME, parse='full')


def send_mpim(user_ids, message):
    api_call = slack_api('mpim.open', users=','.join(user_ids))
    channel_id = api_call.get('group').get('id')
    send_channel_message(channel_id, message)
    return channel_id


def send_channel_message(channel_id, message):
    slack_api('chat.postMessage', channel=channel_id, text=message, username=BOT_NAME, parse='full')


def get_player_list(channel_id):
    users = slack_api("users.list").get('members')
    if channel_id is not None:
        users_in_channel = slack_api("channels.info", channel=channel_id).get('channel').get('members')
    for user in users:
        if 'id' in user and \
           (channel_id is None or user.get('id') in users_in_channel) and \
           'deleted' in user and \
           user.get('deleted') is False and \
           'is_admin' in user and \
           user.get('is_admin') is False and \
           'is_bot' in user and \
           user.get('is_bot') is False and \
           'name' in user and \
           user.get('name') != 'slackbot':
            yield user


def get_channel_id_by_name(channel_name):
    channels = slack_api('channels.list').get('channels')
    for channel in channels:
        if channel['name'] == channel_name:
            return channel['id']

    return None


def parse_slack_output(slack_rtm_output):
    output_list = slack_rtm_output
    if output_list and len(output_list) > 0:
        for output in output_list:
            log('API', output)
            if output and 'type' in output and output['type'] == 'message':
                handle_message_event(output)


def do_daily():
    select_for_pairing()


def handle_message_event(event):
    global storage

    try:
        user_id = event['user']
        # if admin
        if is_admin(user_id):
            # send confirmation message for starting a game
            if storage['status'] == 'wait' and START_COMMAND in event['text'].lower():
                if '#' in event['text']:
                    mentioned_channels = re.search('<#(\w*)\|([a-zA-Z0-9_-]*)\>', event['text'])
                    storage['channel'] = {}
                    storage['channel']['id'] = mentioned_channels.group(1)
                    storage['channel']['name'] = mentioned_channels.group(2)
                    send_im(user_id, MSG_ADMIN_CONFIRM_START_CHANNEL.format(channel=storage['channel']['name']))
                else:
                    channel_id = get_channel_id_by_name('general')
                    storage['channel']['id'] = channel_id
                    storage['channel']['name'] = 'general'
                    send_im(user_id, MSG_ADMIN_CONFIRM_START_TEAM)

                storage['status'] = 'confirm_start'

            # start game if confirmed
            elif storage['status'] == 'confirm_start':
                if 'yes' in event['text'].lower():
                    if storage['channel']['name'] == 'general':
                        send_im(user_id, MSG_ADMIN_STARTING_GAME_TEAM)
                    else:
                        send_im(user_id, MSG_ADMIN_STARTING_GAME_CHANNEL.format(channel=storage['channel']['name']))
                    start_game(storage['channel']['id'])
                else:
                    send_im(user_id, MSG_ADMIN_CONFIRM_START_CANCEL)
                    storage['status'] = 'wait'

            # send confirmation message for stopping a game
            elif storage['status'] == 'game' and STOP_COMMAND in event['text'].lower():
                send_im(user_id, MSG_ADMIN_CONFIRM_STOP)
                storage['status'] = 'confirm_stop'

            # stop game if confirmed
            elif storage['status'] == 'confirm_stop':
                if 'yes' in event['text'].lower():
                    send_im(user_id, MSG_ADMIN_STOPPING_GAME)
                    stop_game()
                else:
                    send_im(user_id, MSG_ADMIN_CONFIRM_STOP_CANCEL)
                    storage['status'] = 'game'
            else:
                send_im(user_id, MSG_ADMIN_UNKNOWN_COMMAND)
        # if player
        else:
            # setup
            if user_id in storage['players'] and storage['players'][user_id]['status'] == 'setup':
                handle_setup(user_id, event['text'])
            # play
            elif user_id in storage['players'] and storage['players'][user_id]['status'] == 'play':
                send_im(user_id, MSG_NOT_YOUR_TURN)
            # answer
            elif user_id in storage['players'] and storage['players'][user_id]['status'] == 'answer':
                if event['channel'] == storage['players'][user_id]['play_channel']:
                    handle_answer(user_id, event['text'])
                else:
                    send_im(user_id, MSG_SAY_IN_MPIM)
            else:
                send_im(user_id, MSG_USER_UNKNOWN_COMMAND)
    except KeyError as e:
        print(e)


# TODO: handle players joining the channel after game start
def start_game(channel_id):
    global storage
    storage['status'] = 'game'
    players = get_player_list(channel_id)
    for player in players:
        # save player status
        # we need player id in key and in value as well
        storage['players'][player['id']] = {
            'id': player['id'],
            'name': player['name'],
            'status': 'setup',
            'current_question_num': 0,
            'questions': [],
            'answers': [],
            'rounds': 0,
            'last_round': None,
            'opponents': [],
            'play_channel': None,
            'points': 0
        }

        player_st = storage['players'][player['id']]
        # send initial messages to player
        send_im(player['id'], MSG_WELCOME)
        send_im(player['id'], MSG_SETUP)
        send_im(player['id'], MSG_QUESTION.format(number=NUMBERS[len(player_st['questions'])]))


# TODO: handle ending game with passing deadline
# TODO: making recurring games
def stop_game():
    global storage
    storage['status'] = 'wait'

    # get top 3 players by points
    players = list(storage['players'].values())
    players.sort(key=lambda p: p['points'], reverse=True)

    # send leaderboard
    send_channel_message(
        storage['channel']['id'],
        MSG_END_GAME.format(
            player_1=players[0]['name'] if len(players) > 0 else '-',
            points_1=players[0]['points'] if len(players) > 0 else '-',
            player_2=players[1]['name'] if len(players) > 1 else '-',
            points_2=players[1]['points'] if len(players) > 1 else '-',
            player_3=players[2]['name'] if len(players) > 2 else '-',
            points_3=players[2]['points'] if len(players) > 2 else '-'
        )
    )


def select_for_pairing():
    """
        Pairing rules:
        - player must be in "play" state
        - a user can play daily once
        - always the players with the least rounds become paired
        (if there are more players with the same number of rounds then we go through in order of storage)
        - nobody can play with the same pair twice in a game
        - nobody can play with themselves
    """
    global storage

    # filter for status and last_round
    players = [value
               for value
               in storage['players'].values()
               if value['status'] == 'ready' and
               value['last_round'] != date.today()]

    # sort by rounds
    players.sort(key=lambda p: p['rounds'], reverse=False)

    # search for a suitable pair
    for player in players:
        candidates = list(filter(lambda p: p['id'] not in player['opponents'] and
                          p['id'] != player['id'], players))
        if len(candidates) > 0:
            candidate = candidates[0]

            # update locale list with players already paired
            candidate['opponents'].append(player['id'])
            player['opponents'].append(candidate['id'])

            # update storage with players already paired
            storage['players'][player['id']]['opponents'].append(candidate['id'])
            storage['players'][candidate['id']]['opponents'].append(player['id'])

            pair_players(player['id'], candidate['id'])


def pair_players(user_id_1, user_id_2):
    global storage
    log('PROGRAM', '{} and {} are going to be paired.'.format(user_id_1, user_id_2))

    # change users' state to play from ready
    storage['players'][user_id_1]['status'] = 'play'
    storage['players'][user_id_2]['status'] = 'play'

    # send group im to the opponents
    channel_id = send_mpim([user_id_1, user_id_2], MSG_ROUND_START)

    # save play channel for future checking
    storage['players'][user_id_1]['play_channel'] = channel_id
    storage['players'][user_id_2]['play_channel'] = channel_id

    ask_question_from_players(user_id_1, user_id_2)


def ask_question_from_players(user_id_1, user_id_2):
    global storage
    player_id = None
    opponent_id = None

    # determine who's playing
    if (storage['players'][user_id_1]['status'] == 'play' or
       storage['players'][user_id_1]['status'] == 'answer'):
        player_id = user_id_1
        opponent_id = user_id_2
    elif (storage['players'][user_id_2]['status'] == 'play' or
          storage['players'][user_id_1]['status'] == 'answer'):
        player_id = user_id_2
        opponent_id = user_id_1
    else:
        # end of round (we can't get here)
        pass

    # if there wasn't any question asked from this player in this round
    if (storage['players'][player_id]['current_question_num'] == 0):
        send_mpim(
            [player_id, opponent_id],
            MSG_ROUND_NEXT_USER.format(user_name=storage['players'][player_id]['name'])
        )
        storage['players'][player_id]['current_question_num'] = 1

    # set up shortcuts
    player_st = storage['players'][player_id]
    current_question_num = player_st['current_question_num']
    question = storage['players'][opponent_id]['questions'][current_question_num - 1]

    # ask the question
    send_mpim(
        [player_id, opponent_id],
        MSG_ROUND_QUESTION.format(
            user_name=player_st['name'],
            number=NUMBERS[current_question_num - 1],
            question=question
        )
    )

    # set status so we are waiting for this player's answer
    player_st['status'] = 'answer'


# TODO: cancel
# TODO: redoable setup
# TODO: profile picture
def handle_setup(user_id, message):
    global storage
    player_st = storage['players'][user_id]
    # question
    if len(player_st['questions']) == len(player_st['answers']):
        send_im(
            user_id,
            MSG_QUESTION_DONE.format(
                number=NUMBERS[len(player_st['questions'])],
                question=message
            )
        )
        player_st['questions'].append(message)
        send_im(user_id, MSG_ANSWER.format(number=NUMBERS[len(player_st['answers'])]))
    # answer
    else:
        answer = None
        if 'true' in message.lower():
            answer = True
        elif 'false' in message.lower():
            answer = False
        else:
            send_im(user_id, MSG_ANSWER_REPEAT.format(number=NUMBERS[len(player_st['answers'])]))

        if answer is not None:
            send_im(
                user_id,
                MSG_ANSWER_DONE.format(
                    number=NUMBERS[len(player_st['answers'])],
                    answer=answer
                )
            )
            player_st['answers'].append(answer)

            # if we're done with the setup
            if len(player_st['questions']) == 3:
                send_im(user_id, MSG_SETUP_DONE)
                player_st['status'] = 'ready'
                select_for_pairing()
            else:
                send_im(user_id, MSG_QUESTION.format(number=NUMBERS[len(player_st['questions'])]))


def handle_answer(user_id, message):
    global storage
    player_st = storage['players'][user_id]
    opponent_st = storage['players'][player_st['opponents'][-1]]
    current_question_num = player_st['current_question_num']

    answer = None
    if 'true' in message.lower():
        answer = True
    elif 'false' in message.lower():
        answer = False
    else:
        send_mpim([user_id, opponent_st['id']], MSG_ROUND_ANSWER_REPEAT.format(user_name=player_st['name']))

    if answer is not None:
        # handle correctness
        if answer == opponent_st['answers'][current_question_num - 1]:
            send_mpim([user_id, opponent_st['id']], MSG_ROUND_ANSWER_CORRECT.format(user_name=player_st['name']))
            player_st['points'] += 1
        else:
            send_mpim([user_id, opponent_st['id']], MSG_ROUND_ANSWER_INCORRECT.format(user_name=player_st['name']))

        # update current question number (or state if we're done)
        if current_question_num == 3:
            player_st['current_question_num'] = 0
            # TODO: could be something else as now we're sending the no game ongoing message to the first user
            #  while the second user still answering the questions
            player_st['status'] = 'ready'
        else:
            player_st['current_question_num'] += 1

        if player_st['status'] == 'ready' and opponent_st['status'] == 'ready':
            # end of round
            player_st['last_round'] = date.today()
            opponent_st['last_round'] = date.today()
            player_st['rounds'] += 1
            opponent_st['rounds'] += 1
            player_st['play_channel'] = None
            opponent_st['play_channel'] = None

            send_mpim([player_st['id'], opponent_st['id']], MSG_ROUND_END)
            send_im(player_st['id'], MSG_ROUND_POINTS.format(points=player_st['points']))
            send_im(opponent_st['id'], MSG_ROUND_POINTS.format(points=opponent_st['points']))
        else:
            # ask next question
            ask_question_from_players(user_id, opponent_st['id'])


def main():
    # 0.1 second delay between reading from firehose
    READ_WEBSOCKET_DELAY = 0.1

    daily_done = False

    if slack_client.rtm_connect():
        log('PROGRAM', 'QuestionBot connected and running!')
        while True:
            parse_slack_output(slack_client.rtm_read())

            # handle daily jobs
            if datetime.now().hour == DAILY_START_HOURS and not daily_done:
                daily_done = True
                do_daily()
            elif datetime.now().hour == 0:
                daily_done = False

            time.sleep(READ_WEBSOCKET_DELAY)
    else:
        log('PROGRAM', 'Connection failed. Invalid Slack token or bot ID?')

if __name__ == "__main__":
    main()
