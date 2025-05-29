import argparse
import random
import time
from concurrent import futures
from typing import Tuple

import grpc
from google.protobuf import json_format
from grpc import RpcError

from internal.handler.coms import game_pb2
from internal.handler.coms import game_pb2_grpc as game_grpc

timeout_to_response = 1  # 1 second


class BotGameTurn:
    def __init__(self, turn, action):
        self.turn = turn
        self.action = action


def energy_efficient_path(start, end):
    sx, sy = start
    ex, ey = end
    dx = ex - sx
    dy = ey - sy



class BotGame:
    def __init__(self, player_num=None):
        self.player_num = player_num
        self.turn_states = []
        self.countT = 0
        self.stuck_counter = 0
        self.max_lighthouses = 4
        self.last_position = None

    def _get_lighthouses_dict(self, turn: game_pb2.NewTurn):
        return {
            (lh.Position.X, lh.Position.Y): lh
            for lh in turn.Lighthouses
        }

    def _choose_connection(self, current_pos, lighthouses):
        possible = []
        for pos, lh in lighthouses.items():
            if (
                    pos != current_pos and
                    lh.HaveKey and
                    current_pos not in [(p.X, p.Y) for p in lh.Connections] and
                    lh.Owner == self.player_num
            ):
                possible.append(pos)
        return random.choice(possible) if possible else None

    def _can_attack(self, lighthouse, my_energy):
        return lighthouse.Energy <= 1.5 * my_energy

    def _find_attackable_lighthouse(self, cx, cy, my_energy, lighthouses):
        best_target = None
        min_dist = float('inf')
        for pos, lh in lighthouses.items():
            if lh.Owner != self.player_num and self._can_attack(lh, my_energy):
                dist = abs(pos[0] - cx) + abs(pos[1] - cy)
                if dist < min_dist:
                    min_dist = dist
                    best_target = pos
        return best_target

    def _move_towards(self, cx, cy, target_pos, turn):
        tx, ty = target_pos
        dx = max(-1, min(1, tx - cx))
        dy = max(-1, min(1, ty - cy))
        nx, ny = cx + dx, cy + dy

        nx = max(0, min(14, nx))
        ny = max(0, min(14, ny))

        return self._build_action(game_pb2.MOVE, (nx, ny), 0, turn)

    def _random_move(self, cx, cy, turn):
        moves = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
        dx, dy = random.choice(moves)
        nx, ny = max(0, min(14, cx + dx)), max(0, min(14, cy + dy))
        return self._build_action(game_pb2.MOVE, (nx, ny), 0, turn)

    def _build_action(self, action_type, pos_tuple, energy, turn):
        action = game_pb2.NewAction(
            Action=action_type,
            Destination=game_pb2.Position(X=pos_tuple[0], Y=pos_tuple[1]),
            Energy=energy
        )
        self.turn_states.append(BotGameTurn(turn, action))
        self.countT += 1
        return action

    def _try_connect(self, lh, lighthouses, turn):
        cx, cy = lh.Position.X, lh.Position.Y
        for dest_pos, dest_lh in lighthouses.items():
            if (dest_pos != (cx, cy) and dest_lh.Owner == self.player_num and dest_lh.HaveKey
                    and [cx, cy] not in dest_lh.Connections):
                return self._build_action(game_pb2.CONNECT, dest_pos, 0, turn)
        return None

    def _find_adjacent_lighthouse(self, cx, cy, lighthouses):
        for dx in [-1, 0, 1]:
            for dy in [-1, 0, 1]:
                if dx == 0 and dy == 0:
                    continue
                pos = (cx + dx, cy + dy)
                if pos in lighthouses:
                    return pos
        return None

    def _find_nearest_any_lighthouse(self, cx, cy, lighthouses):
        return min(lighthouses.keys(), key=lambda pos: abs(pos[0] - cx) + abs(pos[1] - cy), default=None)

    def _find_nearest_owned_lighthouse(self, cx, cy, lighthouses):
        return min(
            [pos for pos, lh in lighthouses.items() if lh.Owner == self.player_num],
            key=lambda pos: abs(pos[0] - cx) + abs(pos[1] - cy),
            default=None
        )

    def _find_attackable_lighthouse(self, cx, cy, my_energy, lighthouses):
        candidates = [
            pos for pos, lh in lighthouses.items()
            if lh.Owner != self.player_num and lh.Energy < my_energy * 1.5
        ]
        return min(candidates, key=lambda pos: abs(pos[0] - cx) + abs(pos[1] - cy), default=None)

    def _move_towards(self, cx, cy, target, turn):
        tx, ty = target
        dx = (tx - cx) and ((tx - cx) // abs(tx - cx))
        dy = (ty - cy) and ((ty - cy) // abs(ty - cy))
        return self._build_action(game_pb2.MOVE, (cx + dx, cy + dy), 0, turn)

    def _move_around(self, target_pos, cx, cy, turn):
        tx, ty = target_pos
        moves = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
        random.shuffle(moves)
        for dx, dy in moves:
            nx, ny = cx + dx, cy + dy
            if abs(nx - tx) <= 1 and abs(ny - ty) <= 1:
                return self._build_action(game_pb2.MOVE, (nx, ny), 0, turn)
        return self._random_move(cx, cy, turn)

    def _random_move(self, cx, cy, turn):
        moves = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
        dx, dy = random.choice(moves)
        return self._build_action(game_pb2.MOVE, (cx + dx, cy + dy), 0, turn)

    def _build_action(self, action_type, dest: Tuple[int, int], energy: int, turn):
        action = game_pb2.NewAction(
            Action=action_type,
            Destination=game_pb2.Position(X=dest[0], Y=dest[1]),
            Energy=energy,
        )
        self.turn_states.append((turn, action))
        self.countT += 1
        return action

    def new_turn_action(self, turn: game_pb2.NewTurn) -> game_pb2.NewAction:
        cx, cy = turn.Position.X, turn.Position.Y
        current_pos = (cx, cy)
        lighthouses = {(lh.Position.X, lh.Position.Y): lh for lh in turn.Lighthouses}

        # Contar faros propios
        owned_lighthouses = [lh for lh in lighthouses.values() if lh.Owner == self.player_num]
        should_attack_more = len(owned_lighthouses) < self.max_lighthouses

        # Detectar si está estancado
        if self.last_position == current_pos:
            self.stuck_counter += 1
        else:
            self.stuck_counter = 0
        self.last_position = current_pos

        # Si poca energía, recargar
        if turn.Energy < 10:
            if current_pos in lighthouses:
                return self._build_action(game_pb2.PASS, current_pos, 0, turn)
            adj = self._find_adjacent_lighthouse(cx, cy, lighthouses)
            if adj:
                return self._move_around(adj, cx, cy, turn)
            nearest = self._find_nearest_any_lighthouse(cx, cy, lighthouses)
            if nearest:
                return self._move_towards(cx, cy, nearest, turn)
            return self._random_move(cx, cy, turn)

        # Si estamos en un faro
        if current_pos in lighthouses:
            lh = lighthouses[current_pos]

            # Si es nuestro, conectar si es posible
            if lh.Owner == self.player_num:
                conn_action = self._try_connect(lh, lighthouses, turn)
                if conn_action:
                    return conn_action

            # Si no es nuestro, atacar si permitido y posible
            elif should_attack_more and lh.Energy < turn.Energy * 1.5:
                energy = min(turn.Energy, lh.Energy + 1)
                return self._build_action(game_pb2.ATTACK, current_pos, energy, turn)

        # Si lleva 2+ turnos en mismo lugar, forzar movimiento
        if self.stuck_counter >= 2:
            self.stuck_counter = 0
            return self._random_move(cx, cy, turn)

        # Mover hacia faro enemigo si aún queremos atacar
        if should_attack_more:
            target = self._find_attackable_lighthouse(cx, cy, turn.Energy, lighthouses)
            if target:
                return self._move_towards(cx, cy, target, turn)

        # Patrullar cerca de nuestros faros
        patrol = self._find_nearest_owned_lighthouse(cx, cy, lighthouses)
        if patrol:
            return self._move_around(patrol, cx, cy, turn)

        return self._random_move(cx, cy, turn)


class BotComs:
    def __init__(self, bot_name, my_address, game_server_address, verbose=False):
        self.bot_id = None
        self.bot_name = bot_name
        self.my_address = my_address
        self.game_server_address = game_server_address
        self.verbose = verbose

    def wait_to_join_game(self):
        channel = grpc.insecure_channel(self.game_server_address)
        client = game_grpc.GameServiceStub(channel)

        player = game_pb2.NewPlayer(name=self.bot_name, serverAddress=self.my_address)

        while True:
            try:
                player_id = client.Join(player, timeout=timeout_to_response)
                self.bot_id = player_id.PlayerID
                print(f"Joined game with ID {player_id.PlayerID}")
                if self.verbose:
                    print(json_format.MessageToJson(player_id))
                break
            except RpcError as e:
                print(f"Could not join game: {e.details()}")
                time.sleep(1)

    def start_listening(self):
        print("Starting to listen on", self.my_address)

        # configure gRPC server
        grpc_server = grpc.server(
            futures.ThreadPoolExecutor(max_workers=10),
            interceptors=(ServerInterceptor(),),
        )

        # registry of the service
        cs = ClientServer(bot_id=self.bot_id, verbose=self.verbose)
        game_grpc.add_GameServiceServicer_to_server(cs, grpc_server)

        # server start
        grpc_server.add_insecure_port(self.my_address)
        grpc_server.start()

        try:
            grpc_server.wait_for_termination()  # wait until server finish
        except KeyboardInterrupt:
            grpc_server.stop(0)


class ServerInterceptor(grpc.ServerInterceptor):
    def intercept_service(self, continuation, handler_call_details):
        start_time = time.time_ns()
        method_name = handler_call_details.method

        # Invoke the actual RPC
        response = continuation(handler_call_details)

        # Log after the call
        duration = time.time_ns() - start_time
        print(f"Unary call: {method_name}, Duration: {duration:.2f} nanoseconds")
        return response


class ClientServer(game_grpc.GameServiceServicer):
    def __init__(self, bot_id, verbose=False):
        self.bg = BotGame(bot_id)
        self.verbose = verbose

    def Join(self, request, context):
        return None

    def InitialState(self, request, context):
        print("Receiving InitialState")
        if self.verbose:
            print(json_format.MessageToJson(request))
        self.bg.initial_state = request
        return game_pb2.PlayerReady(Ready=True)

    def Turn(self, request, context):
        print(f"Processing turn: {self.bg.countT}")
        if self.verbose:
            print(json_format.MessageToJson(request))
        action = self.bg.new_turn_action(request)
        return action


def ensure_params():
    parser = argparse.ArgumentParser(description="Bot configuration")
    parser.add_argument("--bn", type=str, default="random-bot", help="Bot name")
    parser.add_argument("--la", type=str, required=True, help="Listen address")
    parser.add_argument("--gs", type=str, required=True, help="Game server address")

    args = parser.parse_args()

    if not args.bn:
        raise ValueError("Bot name is required")
    if not args.la:
        raise ValueError("Listen address is required")
    if not args.gs:
        raise ValueError("Game server address is required")

    return args.bn, args.la, args.gs


def main():
    verbose = False
    bot_name, listen_address, game_server_address = ensure_params()

    bot = BotComs(
        bot_name=bot_name,
        my_address=listen_address,
        game_server_address=game_server_address,
        verbose=verbose,
    )
    bot.wait_to_join_game()
    bot.start_listening()

def test_pust():
    return True


if __name__ == "__main__":
    main()
