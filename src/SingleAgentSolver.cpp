#include "SingleAgentSolver.h"


double SingleAgentSolver::compute_h_value(const BasicGraph& G, int curr, int goal_id,
                             const vector<pair<int, int> >& goal_location) const
{
    auto heuristic = G.heuristics.find(goal_location[goal_id].first);
    if (heuristic == G.heuristics.end())
    {
        std::cout << "Missing heuristic table for goal location " << goal_location[goal_id].first << std::endl;
        return DBL_MAX;
    }
    double h = heuristic->second[curr];
    goal_id++;
    while (goal_id < (int) goal_location.size())
    {
        heuristic = G.heuristics.find(goal_location[goal_id].first);
        if (heuristic == G.heuristics.end())
        {
            std::cout << "Missing heuristic table for goal location " << goal_location[goal_id].first << std::endl;
            return DBL_MAX;
        }
        h += heuristic->second[goal_location[goal_id - 1].first];
        goal_id++;
    }
    return h;
}
