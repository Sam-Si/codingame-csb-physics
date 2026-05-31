/*
 * replay_driver.cpp
 *
 * Small command-line tool to drive physics.h with exact move sequences
 * extracted from real CodinGame battle replays (test_session_battles or user_battles).
 *
 * Goal: given a starting state + the complete list of actions for all 4 pods
 * every turn, produce the exact same states the referee produced, turn after turn.
 *
 * This lets you validate/fix your physics engine against hundreds of real games
 * that contain collisions, shields, boosts, weird checkpoint crossings, etc.
 *
 * Build:
 *     g++ -std=c++17 -O2 -o replay_driver replay_driver.cpp
 *
 * Usage (JSON mode - recommended):
 *     ./replay_driver --battle ../battles/test_session_battles/battle_891669739.json --turns 5
 *
 * It will output JSON lines with the simulated state after each requested turn
 * so the Python side can diff it against the ground truth from battle_parser.py.
 */

#include "physics.h"
#include <iostream>
#include <fstream>
#include <sstream>
#include <vector>
#include <string>
#include <algorithm>
#include <iomanip>

// NOTE: Full JSON battle parsing is intentionally left to the Python side (battle_parser.py).
// This driver uses a simple text protocol so Python can drive it without any C++ JSON deps.

// -----------------------------------------------------------------------------
// Text protocol driver (Python side does the real battle JSON parsing)
// -----------------------------------------------------------------------------

void print_pod_state(const Game& g, int i) {
    const Pod& p = g.pods[i];
    std::cout << std::fixed << std::setprecision(2);
    std::cout << i << " "
              << p.p.x << " " << p.p.y << " "
              << (int)p.s.x << " " << (int)p.s.y << " "
              << p.angle << " "
              << p.next << " "
              << p.shieldtimer << " "
              << p.boosted << "\n";
}

void run_text_replay() {
    // Simple stdin-driven protocol for the first version.
    // Python sends:
    //   INIT <cp_count> x1 y1 x2 y2 ... laps
    //   START x0 y0 vx0 vy0 ang0 next0 sh0 bo0   x1 y1 ... (4 pods)
    //   T <turn> ax0 ay0 thrust0   ax1 ay1 thrust1  ax2... (4 actions)
    //   STEP
    //   ...
    //   QUIT
    //
    // After each STEP we reply with 4 lines of "pod_idx x y vx vy angle next shield boosted"
    // plus a line "TIMEOUTS t0 t1"

    Game g;
    std::vector<Point> cps;
    int laps = 3;
    bool initialized = false;

    std::string cmd;
    while (std::cin >> cmd) {
        if (cmd == "INIT") {
            int ncp;
            std::cin >> ncp;
            cps.resize(ncp);
            for (int i = 0; i < ncp; ++i) {
                std::cin >> cps[i].x >> cps[i].y;
            }
            std::cin >> laps;
            g.initialize(cps, laps);
            initialized = true;
            std::cout << "OK INIT\nREADY\n";
        } else if (cmd == "SET_POD") {
            int idx;
            double x,y,vx,vy,ang;
            int nxt, sh, bo;
            std::cin >> idx >> x >> y >> vx >> vy >> ang >> nxt >> sh >> bo;
            g.setPodState(idx, x, y, vx, vy, ang, nxt, sh, bo);
            std::cout << "OK SET_POD " << idx << "\nREADY\n";
        } else if (cmd == "SET_TIMEOUTS") {
            int t0, t1;
            std::cin >> t0 >> t1;
            g.setPlayerTimeouts(t0, t1);
            std::cout << "OK TIMEOUTS\nREADY\n";
        } else if (cmd == "ACTION") {
            int pod;
            int tx, ty;
            std::string thrust;
            std::cin >> pod >> tx >> ty >> thrust;
            g.applyAction(pod, tx, ty, thrust);
            std::cout << "OK ACTION " << pod << "\nREADY\n";
        } else if (cmd == "STEP") {
            if (!initialized) {
                std::cout << "ERR not initialized\n";
                continue;
            }
            g.nextTurn();
            for (int i = 0; i < 4; ++i) {
                print_pod_state(g, i);
            }
            std::cout << "TIMEOUTS " << g.playerTimeout[0] << " " << g.playerTimeout[1] << "\n";
            std::cout << "STEP_DONE\n";
        } else if (cmd == "DUMP") {
            // Dump current full state (useful for debugging)
            for (int i = 0; i < 4; ++i) {
                print_pod_state(g, i);
            }
            std::cout << "TIMEOUTS " << g.playerTimeout[0] << " " << g.playerTimeout[1] << "\n";
            std::cout << "DUMP_DONE\n";
        } else if (cmd == "QUIT") {
            break;
        } else {
            std::cout << "ERR unknown cmd " << cmd << "\n";
        }
        std::cout.flush();
    }
}

int main(int argc, char** argv) {
    // For now just run the interactive text protocol.
    // Later add --battle <json> mode that uses full parsing.
    run_text_replay();
    return 0;
}
