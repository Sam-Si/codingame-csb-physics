#pragma once
#include <cmath>
#include <vector>
#include <string>
#include <algorithm>
#include <iostream>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

// GAME CONSTANTS
const double podRSQ = 800.0 * 800.0;
const double cpRSQ = 600.0 * 600.0;
const int podCount = 4;
const double minImpulse = 120.0;
const double frictionVal = 0.85;

// MATH CONSTANTS
const double radToDeg = 180.0 / M_PI;
const double degToRad = M_PI / 180.0;
const double maxRotate = 18.0 * degToRad;
const double EPSILON = 0.00001;

struct Point {
    double x;
    double y;

    double norm() const {
        return std::sqrt(x * x + y * y);
    }
    double dot(const Point& n) const {
        return x * n.x + y * n.y;
    }
    double dist(const Point& n) const {
        return std::sqrt((x - n.x) * (x - n.x) + (y - n.y) * (y - n.y));
    }
};

struct Pod {
    Point p;           // Position
    Point s;           // Velocity
    double angle;      // Facing angle in radians
    int next;          // Next checkpoint index in global checkpoints
    int shieldtimer;   // Shield timer (4 when active, decrements to 0)
    int boosted;       // Boost used flag (0 = available, 1 = used)
    bool won;          // Won flag
    bool isFirstTurn;  // True until the first applyAction call

    double diffAngle(Point target) const {
        double a = std::atan2(target.y - p.y, target.x - p.x);
        double da = std::fmod(a - angle, 2.0 * M_PI);
        if (da < -M_PI) da += 2.0 * M_PI;
        if (da > M_PI) da -= 2.0 * M_PI;
        return da;
    }

    void applyRotate(Point target) {
        double a = std::atan2(target.y - p.y, target.x - p.x);
        double rotateAngle = diffAngle(target);
        if (rotateAngle < -maxRotate) {
            a = angle - maxRotate;
        } else if (rotateAngle > maxRotate) {
            a = angle + maxRotate;
        }
        angle = a;
    }

    void applyRotateFirst(double rotateAngle) {
        // First turn: set angle directly (no 18° clamp).
        // Keep in [-π, π] to match the referee's atan2 convention.
        angle = rotateAngle;
    }

    void applyThrust(int t) {
        double cc = std::cos(angle);
        double cs = std::sin(angle);
        s.x += cc * t;
        s.y += cs * t;
    }

    void endTurn() {
        s.x = std::trunc(s.x * frictionVal);
        s.y = std::trunc(s.y * frictionVal);

        p.x = std::floor(p.x + 0.5);
        p.y = std::floor(p.y + 0.5);

        if (shieldtimer > 0) {
            shieldtimer--;
        }
    }

    double newCollide(const Pod* b, double rsq) const {
        Point rel_p = {b->p.x - p.x, b->p.y - p.y};
        double pLength2 = rel_p.x * rel_p.x + rel_p.y * rel_p.y;

        if (pLength2 <= rsq) {
            return 0.0;
        }

        Point v = {b->s.x - s.x, b->s.y - s.y};
        double dot = rel_p.dot(v);

        if (dot > 0.0) {
            return 10.0;
        }

        double vLength2 = v.x * v.x + v.y * v.y;
        if (vLength2 == 0.0) {
            return 10.0;
        }
        double disc = dot * dot - vLength2 * (pLength2 - rsq);

        if (disc < 0.0) {
            return 10.0;
        }

        double discdist = std::sqrt(disc);
        double t1 = (-dot - discdist) / vLength2;
        return t1;
    }

    void passCheckpoint(int podn, const std::vector<Point>& globalCp, std::vector<int>& playerTimeout) {
        next = next + 1;
        if (next >= (int)globalCp.size()) {
            next = (int)globalCp.size() - 1;
            won = true;
        }
        if (podn < 2) {
            playerTimeout[0] = 101;
        } else {
            playerTimeout[1] = 101;
        }
    }
};

inline bool cpCollide(Point p1, Point p2, Point cp, double cpRSQ) {
    double dx = p2.x - p1.x;
    double dy = p2.y - p1.y;
    Point pp = p1;
    double pd2 = dx * dx + dy * dy;

    if (pd2 != 0.0) {
        double u = ((cp.x - p1.x) * dx + (cp.y - p1.y) * dy) / pd2;
        if (u > 1.0) {
            pp = p2;
        } else if (u > 0.0) {
            pp.x = p1.x + u * dx;
            pp.y = p1.y + u * dy;
        }
    }

    pp.x -= cp.x;
    pp.y -= cp.y;
    double distSQ = pp.x * pp.x + pp.y * pp.y;
    if (distSQ < cpRSQ) {
        return true;
    }
    return false;
}

struct Game {
    std::vector<Pod> pods;
    std::vector<Point> globalCp;
    std::vector<int> playerTimeout;

    Game() {
        pods.resize(4);
        playerTimeout = {100, 100};
    }

    // Load exact state for a pod (useful for replay validation against real battles)
    void setPodState(int pod_idx, double x, double y, double vx, double vy,
                     double angle_rad, int next_cp, int shield_timer, int has_boosted) {
        if (pod_idx < 0 || pod_idx >= 4) return;
        Pod& p = pods[pod_idx];
        p.p = {x, y};
        p.s = {vx, vy};
        p.angle = angle_rad;
        p.next = next_cp;
        p.shieldtimer = shield_timer;
        p.boosted = has_boosted;
        p.won = false;
        // Detect first turn from sentinel angle value (-0.0174533 is what we pass for null/init)
        p.isFirstTurn = (std::abs(angle_rad + 0.0174533) < 0.001) || (std::abs(angle_rad) < 0.001);
    }

    void setPlayerTimeouts(int t0, int t1) {
        playerTimeout[0] = t0;
        playerTimeout[1] = t1;
    }

    // Apply one pod's command for the turn (rotation + thrust/shield/boost).
    // Must be called for all 4 pods before nextTurn().
    // thrust_str: "200", "0", "BOOST", "SHIELD"
    void applyAction(int pod_idx, int target_x, int target_y, const std::string& thrust_str) {
        if (pod_idx < 0 || pod_idx >= 4) return;
        Pod& p = pods[pod_idx];
        Point target = {(double)target_x, (double)target_y};

        if (p.isFirstTurn) {
            p.isFirstTurn = false;
            // First round: angle set directly, no 18° limit (per rules + bot stderr observations)
            double a = std::atan2(target.y - p.p.y, target.x - p.p.x);
            p.applyRotateFirst(a);
        } else {
            p.applyRotate(target);
        }

        int thrust = 0;
        bool used_shield = false;

        if (thrust_str == "SHIELD") {
            p.shieldtimer = 4;   // becomes active for this turn's collision phase (mass*10)
            used_shield = true;
            thrust = 0;
        } else if (thrust_str == "BOOST") {
            // Boost is per-pod: each pod can BOOST once per game (verified from battle data:
            // both pods of a player can BOOST on the same turn, each gets thrust=650).
            if (p.boosted == 0) {
                thrust = 650;
                p.boosted = 1;
            } else {
                // Already used boost → treat as max normal thrust
                thrust = 200;
            }
        } else {
            try {
                thrust = std::stoi(thrust_str);
            } catch (...) {
                thrust = 0;
            }
            if (thrust < 0) thrust = 0;
            if (thrust > 200) thrust = 200;
        }

        // During shield cooldown the pod cannot accelerate (thrust forced to 0).
        // This includes the turn the shield is activated (shieldtimer==4).
        // If BOOST was requested during cooldown, the boost is NOT consumed.
        if (!used_shield && p.shieldtimer > 0) {
            if (thrust_str == "BOOST" && p.boosted == 1) {
                // Undo the boost consumption — pod can't thrust during cooldown
                p.boosted = 0;
            }
            thrust = 0;
        }

        p.applyThrust(thrust);
    }

    void initialize(const std::vector<Point>& track, int laps = 3) {
        globalCp.clear();
        for (int i = 0; i < laps; ++i) {
            for (const auto& cp : track) {
                globalCp.push_back(cp);
            }
        }
        // Add final checkpoint
        globalCp.push_back(track[0]);

        // Setup pods using standard referee startPointMult
        const std::vector<Point> startPointMult = {
            {500.0, -500.0}, {-500.0, 500.0}, {1500.0, -1500.0}, {-1500.0, 1500.0}
        };

        double dx = track[1].x - track[0].x;
        double dy = track[1].y - track[0].y;
        double dd = std::sqrt(dx * dx + dy * dy);
        Point cp1minus0 = {dx / dd, dy / dd};

        for (int podN = 0; podN < 4; ++podN) {
            Pod& p = pods[podN];
            p.angle = -1.0 * degToRad;
            p.next = 1;
            p.shieldtimer = 0;
            p.boosted = 0;
            p.won = false;
            p.isFirstTurn = true;
            p.s = {0.0, 0.0};
            p.p.x = std::floor(track[0].x + cp1minus0.y * startPointMult[podN].x + 0.5);
            p.p.y = std::floor(track[0].y + cp1minus0.x * startPointMult[podN].y + 0.5);
        }

        playerTimeout = {100, 100};
    }

    void forwardTime(double t) {
        for (int i = 0; i < podCount; ++i) {
            pods[i].p.x += pods[i].s.x * t;
            pods[i].p.y += pods[i].s.y * t;
        }
    }

    void bounce(int p1, int p2) {
        Pod* oa = &pods[p1];
        Pod* ob = &pods[p2];

        Point normal = {ob->p.x - oa->p.x, ob->p.y - oa->p.y};
        double dd = normal.norm();
        normal.x /= dd;
        normal.y /= dd;

        Point relv = {oa->s.x - ob->s.x, oa->s.y - ob->s.y};

        double m1 = 1.0;
        double m2 = 1.0;
        if (oa->shieldtimer == 4) m1 = 0.1;
        if (ob->shieldtimer == 4) m2 = 0.1;

        double force = normal.dot(relv) / (m1 + m2);
        if (force < 120.0) {
            force += 120.0;
        } else {
            force += force;
        }

        Point impulse = normal;
        impulse.x *= -force;
        impulse.y *= -force;

        oa->s.x += impulse.x * m1;
        oa->s.y += impulse.y * m1;
        ob->s.x += -impulse.x * m2;
        ob->s.y += -impulse.y * m2;

        if (dd <= 800.0) {
            double dist_diff = dd - 800.0;
            oa->p.x += normal.x * -(-dist_diff / 2.0 + EPSILON);
            oa->p.y += normal.y * -(-dist_diff / 2.0 + EPSILON);
            ob->p.x += normal.x * (-dist_diff / 2.0 + EPSILON);
            ob->p.y += normal.y * (-dist_diff / 2.0 + EPSILON);
        }
    }

    void nextTurn() {
        double t = 1.0;
        std::vector<Point> curps = {pods[0].p, pods[1].p, pods[2].p, pods[3].p};

        while (t > 0.0) {
            double first = t;
            int cli = 0;
            int clj = 0;

            for (int i = podCount - 1; i > 0; --i) {
                for (int j = i - 1; j >= 0; --j) {
                    double tx = pods[i].newCollide(&pods[j], podRSQ);
                    if (tx <= first) {
                        first = tx;
                        cli = i;
                        clj = j;
                    }
                }
            }

            forwardTime(first);
            t -= first;

            if (cli != clj) {
                bounce(cli, clj);
            }

            if (t > 0.0) {
                for (int i = 0; i < podCount; ++i) {
                    if (cpCollide(curps[i], pods[i].p, globalCp[pods[i].next], cpRSQ)) {
                        pods[i].passCheckpoint(i, globalCp, playerTimeout);
                    }
                }
                curps = {pods[0].p, pods[1].p, pods[2].p, pods[3].p};
            }
        }

        for (int i = 0; i < podCount; ++i) {
            pods[i].endTurn();
            if (cpCollide(curps[i], pods[i].p, globalCp[pods[i].next], cpRSQ)) {
                pods[i].passCheckpoint(i, globalCp, playerTimeout);
            }
        }

        playerTimeout[0]--;
        playerTimeout[1]--;
    }
};
