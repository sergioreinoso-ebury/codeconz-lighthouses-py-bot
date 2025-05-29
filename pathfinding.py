Point = tuple[int, int]

MOVEMENTS = [
    (mi, mj) for mi in (-1, 0, 1) for mj in (-1, 0, 1) if mi or mj
]

def _center_view(view: list[list[int]]):
    view_distance = len(view) // 2
    centered_view = {
        (i - view_distance, j - view_distance): energy
            for i, row in enumerate(view)
            for j, energy in enumerate(row)
    }
    return centered_view, view_distance


def next_move(start: Point, end: Point, view: list[list[int]]):
    start_i, start_j = start
    end_i, end_j = end

    centered_view, view_distance = _center_view(view)

    rel_end_i = end_i - start_i
    rel_end_j = end_j - start_j
    energy, remaining, moves = max(_energy_efficient_path(view_distance, (0, 0), (rel_end_i, rel_end_j), centered_view, 1, 0, ()))
    return moves[0]

def _energy_efficient_path(
                           view_distance: int,
                           start: Point,
                           end: Point,
                           centered_view: dict[Point, int],
                           extra_turns: int,
                           gained_energy: int,
                           path: tuple[Point, ...]):
    start_i, start_j = start
    end_i, end_j = end

    if start == end or max(abs(start_i), abs(start_j)) == view_distance:
        yield gained_energy, -extra_turns, path
        return
    
    di = end_i - start_i
    dj = end_j - start_j
    norm_0 = max(abs(di), abs(dj))

    for mi, mj in MOVEMENTS:
        movement = mi, mj
        next_i, next_j = start_i + mi, start_j + mj
        next_position = next_i, next_j
        if next_position in centered_view:
            next_norm_0 = max(abs(end_i - next_i), abs(end_j - next_j))
            next_energy = gained_energy + centered_view[(next_i, next_j)]
            next_path = path + (movement,)
            if next_norm_0 <= norm_0:
                yield from _energy_efficient_path(view_distance, next_position, end, centered_view, extra_turns, next_energy, next_path)
            elif extra_turns and next_norm_0 == norm_0 + 1:
                yield from _energy_efficient_path(view_distance, next_position, end, centered_view, extra_turns - 1, next_energy, next_path)

