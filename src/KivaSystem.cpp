#include "KivaSystem.h"
#include "WHCAStar.h"
#include "ECBS.h"
#include "LRAStar.h"
#include "PBS.h"
#include <cmath>
#include <fstream>
#include <sstream>

KivaSystem::KivaSystem(KivaGrid& G, MAPFSolver& solver): BasicSystem(G, solver), G(G) {}


KivaSystem::~KivaSystem()
{
}

bool KivaSystem::load_task_assignments(string fname)
{
	if (fname.empty())
		return false;

	clock_t t = clock();
	string line;
	std::ifstream myfile(fname.c_str());
	if (!myfile.is_open())
	{
		std::cout << "Task file " << fname << " does not exist. " << std::endl;
		return false;
	}

	task_sequences.clear();
	task_sequences.resize(num_of_drives);
	vector<int> task_locations;
	bool any_tasks = false;
	int line_id = 0;
	while (getline(myfile, line))
	{
		line_id++;
		std::size_t comment = line.find('#');
		if (comment != string::npos)
			line = line.substr(0, comment);
		for (auto& c : line)
		{
			if (c == ',' || c == ';' || c == ':')
				c = ' ';
		}

		std::istringstream iss(line);
		vector<int> values;
		int value;
		while (iss >> value)
			values.emplace_back(value);
		if (values.empty())
			continue;
		if (values.size() < 3 || values.size() % 2 == 0)
		{
			std::cout << "Invalid pickup-delivery task line " << line_id
				<< ". Expected: agent_id pickup delivery [pickup delivery ...]" << std::endl;
			return false;
		}

		int agent = values.front();
		list<pair<int, int> > sequence;
		for (int i = 1; i < (int)values.size(); i += 2)
		{
			int pickup = values[i];
			int delivery = values[i + 1];
			if (pickup < 0 || pickup >= (int)G.types.size() || G.types[pickup] == "Obstacle" ||
				delivery < 0 || delivery >= (int)G.types.size() || G.types[delivery] == "Obstacle")
			{
				std::cout << "Invalid pickup-delivery location on task line " << line_id << std::endl;
				return false;
			}
			sequence.emplace_back(pickup, 0);
			sequence.emplace_back(delivery, 0);
			task_locations.emplace_back(pickup);
			task_locations.emplace_back(delivery);
		}

		if (agent == 0)
		{
			task_sequences.emplace_back(sequence);
		}
		else if (1 <= agent && agent <= num_of_drives)
		{
			task_sequences[agent - 1].splice(task_sequences[agent - 1].end(), sequence);
		}
		else
		{
			std::cout << "Invalid agent id " << agent << " on task line " << line_id << std::endl;
			return false;
		}
		any_tasks = true;
	}
	myfile.close();
	G.ensure_heuristics(task_locations);
	loading_time = (clock() - t) * 1.0 / CLOCKS_PER_SEC;
	task_assignments_loaded = any_tasks;
	return task_assignments_loaded;
}

void KivaSystem::initialize()
{
	initialize_solvers();

	starts.resize(num_of_drives);
	goal_locations.resize(num_of_drives);
	paths.resize(num_of_drives);
	finished_tasks.resize(num_of_drives);
	final_return_locations.assign(num_of_drives, -1);
	final_return_assigned.assign(num_of_drives, false);
	final_return_completed.assign(num_of_drives, false);
	temporary_hold_goal.assign(num_of_drives, false);
	final_return_phase = false;
	breakdown_triggered = false;
	breakdown_arrived = false;
	validate_breakdown_config();
	bool succ = load_records(); // continue simulating from the records
	if (!succ)
	{
		timestep = 0;
		succ = load_locations();
		if (!succ)
		{
			cout << "Randomly generating initial locations" << endl;
			initialize_start_locations();
			initialize_goal_locations();
		}
	}
	record_initial_start_locations();
	if (timestep == 0 && has_task_assignments())
		print_estimate();
	if (breakdown_enabled() && breakdown_after_tasks == 0)
		trigger_breakdown();
}

void KivaSystem::initialize_start_locations()
{
	// Choose random start locations
	// Any non-obstacle locations can be start locations
	// Start locations should be unique
	for (int k = 0; k < num_of_drives; k++)
	{
		int orientation = -1;
		if (consider_rotation)
		{
			orientation = rand() % 4;
		}
		starts[k] = State(G.agent_home_locations[k], 0, orientation);
		paths[k].emplace_back(starts[k]);
		finished_tasks[k].emplace_back(G.agent_home_locations[k], 0);
	}
}


void KivaSystem::initialize_goal_locations()
{
	if (hold_endpoints || useDummyPaths || has_task_assignments())
		return;
	// Choose random goal locations
	// Goal locations are not necessarily unique
	for (int k = 0; k < num_of_drives; k++)
	{
		int goal = G.endpoints[rand() % (int)G.endpoints.size()];
		goal_locations[k].emplace_back(goal, 0);
	}
}

bool KivaSystem::breakdown_enabled() const
{
	return breakdown_agent >= 0 || breakdown_after_tasks >= 0 || breakdown_location >= 0;
}

void KivaSystem::validate_breakdown_config()
{
	if (!breakdown_enabled())
		return;
	if (breakdown_agent < 0 || breakdown_agent >= num_of_drives)
	{
		std::cout << "ERROR: breakdown_agent must be in [0, " << num_of_drives - 1 << "]." << std::endl;
		exit(-1);
	}
	if (breakdown_after_tasks < 0)
	{
		std::cout << "ERROR: breakdown_after_tasks must be non-negative." << std::endl;
		exit(-1);
	}
	if (breakdown_location < 0 || breakdown_location >= G.size())
	{
		std::cout << "ERROR: breakdown_location must be in [0, " << G.size() - 1 << "]." << std::endl;
		exit(-1);
	}
	if (G.types[breakdown_location] == "Obstacle")
	{
		std::cout << "ERROR: breakdown_location " << breakdown_location << " is an obstacle." << std::endl;
		exit(-1);
	}
	G.ensure_heuristics(vector<int>(1, breakdown_location));
}

void KivaSystem::maintain_breakdown_goal()
{
	if (!breakdown_enabled() || !breakdown_triggered)
		return;

	int release_time = 0;
	if ((int)paths[breakdown_agent].size() > timestep &&
		paths[breakdown_agent][timestep].location == breakdown_location)
	{
		breakdown_arrived = true;
		release_time = timestep + simulation_window + 1;
	}

	goal_locations[breakdown_agent].clear();
	goal_locations[breakdown_agent].emplace_back(breakdown_location, release_time);
}

void KivaSystem::requeue_breakdown_agent_goals()
{
	list<pair<int, int> > carry;
	auto requeue_goal = [&](const pair<int, int>& goal)
	{
		carry.emplace_back(goal);
		if (carry.size() == 2)
		{
			task_sequences.emplace_back(carry);
			carry.clear();
		}
	};
	if (task_sequences.size() > (std::size_t)breakdown_agent)
	{
		for (const auto& goal : task_sequences[breakdown_agent])
			requeue_goal(goal);
		task_sequences[breakdown_agent].clear();
	}
	for (const auto& goal : goal_locations[breakdown_agent])
		requeue_goal(goal);
	if (!carry.empty())
		task_sequences.emplace_back(carry);
	goal_locations[breakdown_agent].clear();
}

void KivaSystem::trigger_breakdown()
{
	if (breakdown_triggered)
		return;
	breakdown_triggered = true;
	breakdown_arrived = false;
	requeue_breakdown_agent_goals();
	goal_locations[breakdown_agent].emplace_back(breakdown_location, 0);
	std::cout << "Breakdown triggered for agent " << breakdown_agent
		<< " after " << breakdown_after_tasks << " tasks; retreating to location "
		<< breakdown_location << "." << std::endl;
}

void KivaSystem::update_breakdown_after_finished_goal(int agent)
{
	if (!breakdown_enabled() || breakdown_triggered || !has_task_assignments() || final_return_phase)
		return;
	if (agent != breakdown_agent)
		return;

	int completed_task_goals = std::max(0, (int)finished_tasks[agent].size() - 1);
	bool completed_delivery = completed_task_goals > 0 && completed_task_goals % 2 == 0;
	if (!completed_delivery)
		return;

	int completed_tasks = completed_task_goals / 2;
	if (completed_tasks >= breakdown_after_tasks)
		trigger_breakdown();
}

bool KivaSystem::has_task_assignments() const
{
	return task_assignments_loaded;
}

bool KivaSystem::has_remaining_task_assignments() const
{
	for (const auto& tasks : task_sequences)
	{
		if (!tasks.empty())
			return true;
	}
	return false;
}

bool KivaSystem::assign_next_task(int agent)
{
	if (breakdown_enabled() && breakdown_triggered && agent == breakdown_agent)
		return false;
	if (final_return_assigned.size() > agent && final_return_assigned[agent])
		return false;
	if (task_sequences.size() <= agent)
		return false;
	if (task_sequences[agent].empty())
	{
		if (task_sequences.size() <= (std::size_t)num_of_drives)
			return false;
		task_sequences[agent] = task_sequences[num_of_drives];
		task_sequences.erase(task_sequences.begin() + num_of_drives);
	}
	auto next = task_sequences[agent].front();
	task_sequences[agent].pop_front();
	goal_locations[agent].emplace_back(next);
	return true;
}

void KivaSystem::record_initial_start_locations()
{
	initial_start_locations.resize(num_of_drives);
	for (int k = 0; k < num_of_drives; k++)
	{
		if (!paths[k].empty())
			initial_start_locations[k] = paths[k].front().location;
		else
			initial_start_locations[k] = starts[k].location;
	}
}

bool KivaSystem::assign_final_return_goal(int agent)
{
	if (final_return_assigned.size() <= agent)
		final_return_assigned.resize(num_of_drives, false);
	if (final_return_assigned[agent])
		return true;
	if (initial_start_locations.size() <= agent)
		record_initial_start_locations();

	if (breakdown_enabled() && breakdown_triggered && agent == breakdown_agent)
	{
		final_return_locations[agent] = breakdown_location;
		goal_locations[agent].clear();
		goal_locations[agent].emplace_back(breakdown_location, timestep + simulation_window + 1);
		final_return_assigned[agent] = true;
		final_return_completed[agent] = (starts[agent].location == breakdown_location);
		return true;
	}

	if (G.agent_home_locations.size() < (std::size_t)num_of_drives)
	{
		std::cout << "ERROR: The map does not have enough home locations for the final return phase." << std::endl;
		return false;
	}

	unordered_set<int> reserved_locations;
	for (int k = 0; k < num_of_drives; k++)
	{
		if (final_return_assigned[k])
			reserved_locations.insert(final_return_locations[k]);
	}

	int best_candidate = -1;
	double best_distance = DBL_MAX;
	for (int candidate : G.agent_home_locations)
	{
		if (candidate == initial_start_locations[agent] || reserved_locations.find(candidate) != reserved_locations.end())
			continue;

		auto heuristic = G.heuristics.find(candidate);
		if (heuristic == G.heuristics.end() || starts[agent].location < 0 ||
			starts[agent].location >= (int)heuristic->second.size() ||
			heuristic->second[starts[agent].location] >= DBL_MAX)
		{
			continue;
		}
		double distance = heuristic->second[starts[agent].location];
		if (distance < best_distance)
		{
			best_distance = distance;
			best_candidate = candidate;
		}
	}

	if (best_candidate >= 0)
	{
		final_return_locations[agent] = best_candidate;
		goal_locations[agent].emplace_back(best_candidate, 0);
		final_return_assigned[agent] = true;
		return true;
	}

	std::cout << "ERROR: No reachable unused home location is available for agent " << agent << "." << std::endl;
	return false;
}

bool KivaSystem::all_final_returns_assigned() const
{
	if (!has_task_assignments())
		return false;
	if ((int)final_return_assigned.size() < num_of_drives)
		return false;
	for (int k = 0; k < num_of_drives; k++)
	{
		if (!final_return_assigned[k])
			return false;
	}
	return true;
}

bool KivaSystem::all_final_returns_completed() const
{
	if (!has_task_assignments())
		return false;
	if ((int)final_return_completed.size() < num_of_drives)
		return false;
	for (int k = 0; k < num_of_drives; k++)
	{
		if (breakdown_enabled() && breakdown_triggered && k == breakdown_agent && breakdown_arrived)
			continue;
		if (!final_return_completed[k])
			return false;
	}
	return true;
}

void KivaSystem::start_final_return_phase_if_ready()
{
	if (!has_task_assignments() || final_return_phase || has_remaining_task_assignments())
		return;
	for (int k = 0; k < num_of_drives; k++)
	{
		if (breakdown_enabled() && breakdown_triggered && k == breakdown_agent)
			continue;
		if (!goal_locations[k].empty())
			return;
	}
	for (int k = 0; k < num_of_drives; k++)
	{
		if (!assign_final_return_goal(k))
			exit(-1);
	}
	final_return_phase = true;
}

void KivaSystem::update_final_return_completion_by_position()
{
	if (!final_return_phase)
		return;
	int end_timestep = std::min(timestep + simulation_window, simulation_time);
	for (int k = 0; k < num_of_drives; k++)
	{
		if (breakdown_enabled() && breakdown_triggered && k == breakdown_agent && breakdown_arrived)
		{
			final_return_completed[k] = true;
			continue;
		}
		if (final_return_locations.size() > k && final_return_locations[k] >= 0 &&
			(int)paths[k].size() > end_timestep &&
			paths[k][end_timestep].location == final_return_locations[k])
		{
			final_return_completed[k] = true;
		}
		else
		{
			final_return_completed[k] = false;
		}
	}
}

bool KivaSystem::solve_final_return()
{
	vector<State> new_starts;
	vector<vector<pair<int, int> > > new_goal_locations;
	vector<Path> planned_paths(num_of_drives);
	new_agents.clear();

	int reservation_horizon = simulation_window;
	if (planning_window > 0 && planning_window < INT_MAX / 2)
		reservation_horizon = std::max(reservation_horizon, planning_window);
	reservation_horizon += k_robust + 2;

	solver.clear();
	solver.initial_rt.clear();
	solver.initial_rt.hold_endpoints = true;
	solver.initial_rt.map_size = G.size();
	solver.initial_rt.k_robust = k_robust;
	solver.initial_rt.window = INT_MAX;
	update_initial_constraints(solver.initial_constraints);

	for (int k = 0; k < num_of_drives; k++)
	{
		if (breakdown_enabled() && breakdown_triggered && k == breakdown_agent && breakdown_arrived)
		{
			final_return_completed[k] = true;
			planned_paths[k].reserve(reservation_horizon + 1);
			for (int t = 0; t <= reservation_horizon; t++)
				planned_paths[k].emplace_back(breakdown_location, t, starts[k].orientation);
			solver.initial_rt.insertPath2CT(planned_paths[k]);
		}
		else if (starts[k].location == final_return_locations[k])
		{
			final_return_completed[k] = true;
			planned_paths[k].reserve(reservation_horizon + 1);
			for (int t = 0; t <= reservation_horizon; t++)
				planned_paths[k].emplace_back(starts[k].location, t, starts[k].orientation);
			solver.initial_rt.insertPath2CT(planned_paths[k]);
		}
		else
		{
			final_return_completed[k] = false;
			new_agents.emplace_back(k);
			new_starts.emplace_back(starts[k]);
			new_goal_locations.push_back(vector<pair<int, int> >(1, make_pair(final_return_locations[k], 0)));
			goal_locations[k].clear();
			goal_locations[k].emplace_back(final_return_locations[k], 0);
		}
	}

	if (!new_agents.empty())
	{
		bool sol;
		if (timestep == 0)
			sol = solver.run(new_starts, new_goal_locations, 10 * time_limit);
		else
			sol = solver.run(new_starts, new_goal_locations, time_limit);

		if (sol)
		{
			auto pt = solver.solution.begin();
			for (int i : new_agents)
			{
				planned_paths[i] = *pt;
				++pt;
			}
		}
		else
		{
			sol = solve_by_WHCA(planned_paths, new_starts, new_goal_locations);
			if (!sol)
				return false;
		}
		if (check_collisions(planned_paths))
		{
			cout << "COLLISIONS!" << endl;
			exit(-1);
		}
	}

	update_paths(planned_paths, INT_MAX);
	solver.save_results(outfile + "/solver.csv", std::to_string(timestep) + ","
		+ std::to_string(num_of_drives) + "," + std::to_string(seed));
	return true;
}

bool KivaSystem::is_stationary_rest_agent(int agent) const
{
	if (breakdown_enabled() && breakdown_triggered && breakdown_arrived && agent == breakdown_agent)
		return true;
	return final_return_completed.size() > agent && final_return_completed[agent] &&
		final_return_locations.size() > agent && final_return_locations[agent] >= 0;
}

int KivaSystem::stationary_rest_location(int agent) const
{
	if (breakdown_enabled() && breakdown_triggered && breakdown_arrived && agent == breakdown_agent)
		return breakdown_location;
	return final_return_locations[agent];
}

bool KivaSystem::solve_with_stationary_holds()
{
	vector<State> new_starts;
	vector<vector<pair<int, int> > > new_goal_locations;
	vector<Path> planned_paths(num_of_drives);
	new_agents.clear();

	int reservation_horizon = simulation_window;
	if (planning_window > 0 && planning_window < INT_MAX / 2)
		reservation_horizon = std::max(reservation_horizon, planning_window);
	reservation_horizon += k_robust + 2;

	solver.clear();
	solver.initial_rt.clear();
	solver.initial_rt.hold_endpoints = true;
	solver.initial_rt.map_size = G.size();
	solver.initial_rt.k_robust = k_robust;
	solver.initial_rt.window = INT_MAX;
	update_initial_constraints(solver.initial_constraints);

	for (int k = 0; k < num_of_drives; k++)
	{
		if (is_stationary_rest_agent(k))
		{
			int rest_location = stationary_rest_location(k);
			planned_paths[k].reserve(reservation_horizon + 1);
			for (int t = 0; t <= reservation_horizon; t++)
				planned_paths[k].emplace_back(rest_location, t, starts[k].orientation);
			solver.initial_rt.insertPath2CT(planned_paths[k]);
		}
		else
		{
			new_agents.emplace_back(k);
			new_starts.emplace_back(starts[k]);
			new_goal_locations.emplace_back(goal_locations[k]);
		}
	}

	if (!new_agents.empty())
	{
		bool sol;
		if (timestep == 0)
			sol = solver.run(new_starts, new_goal_locations, 10 * time_limit);
		else
			sol = solver.run(new_starts, new_goal_locations, time_limit);

		if (sol)
		{
			auto pt = solver.solution.begin();
			for (int i : new_agents)
			{
				planned_paths[i] = *pt;
				++pt;
			}
		}
		else
		{
			sol = solve_by_WHCA(planned_paths, new_starts, new_goal_locations);
			if (!sol)
				return false;
		}
		if (check_collisions(planned_paths))
		{
			cout << "COLLISIONS!" << endl;
			exit(-1);
		}
	}

	update_paths(planned_paths, INT_MAX);
	solver.save_results(outfile + "/solver.csv", std::to_string(timestep) + ","
		+ std::to_string(num_of_drives) + "," + std::to_string(seed));
	return true;
}

void KivaSystem::add_temporary_hold_goals()
{
	temporary_hold_goal.assign(num_of_drives, false);
	vector<int> hold_locations;
	for (int k = 0; k < num_of_drives; k++)
	{
		if (goal_locations[k].empty())
			hold_locations.emplace_back(paths[k][timestep].location);
	}
	G.ensure_heuristics(hold_locations);
	for (int k = 0; k < num_of_drives; k++)
	{
		if (goal_locations[k].empty())
		{
			goal_locations[k].emplace_back(paths[k][timestep].location, timestep + simulation_window + 1);
			temporary_hold_goal[k] = true;
		}
	}
}

void KivaSystem::remove_temporary_hold_goals()
{
	for (int k = 0; k < num_of_drives; k++)
	{
		if (temporary_hold_goal[k] && !goal_locations[k].empty())
			goal_locations[k].clear();
	}
	temporary_hold_goal.assign(num_of_drives, false);
}

void KivaSystem::print_estimate() const
{
	vector<double> route_lengths(num_of_drives, 0);
	vector<int> current_locations = initial_start_locations;
	auto travel_time = [this](int from, int to)
	{
		auto heuristic = G.heuristics.find(to);
		if (heuristic == G.heuristics.end() || from < 0 || from >= (int)heuristic->second.size())
			return (double)G.get_Manhattan_distance(from, to);
		return heuristic->second[from];
	};
	auto append_route = [&](int agent, const list<pair<int, int> >& route)
	{
		for (const auto& goal : route)
		{
			route_lengths[agent] += travel_time(current_locations[agent], goal.first);
			current_locations[agent] = goal.first;
		}
	};

	for (int k = 0; k < num_of_drives && k < (int)task_sequences.size(); k++)
		append_route(k, task_sequences[k]);

	for (int task = num_of_drives; task < (int)task_sequences.size(); task++)
	{
		if (task_sequences[task].empty())
			continue;
		int best_agent = 0;
		double best_finish_time = DBL_MAX;
		for (int k = 0; k < num_of_drives; k++)
		{
			double finish_time = route_lengths[k] +
				travel_time(current_locations[k], task_sequences[task].front().first);
			if (finish_time < best_finish_time)
			{
				best_finish_time = finish_time;
				best_agent = k;
			}
		}
		append_route(best_agent, task_sequences[task]);
	}

	unordered_set<int> reserved_homes;
	for (int k = 0; k < num_of_drives; k++)
	{
		int original_index = -1;
		for (int i = 0; i < (int)G.agent_home_locations.size(); i++)
		{
			if (G.agent_home_locations[i] == initial_start_locations[k])
			{
				original_index = i;
				break;
			}
		}
		if (original_index < 0 || G.agent_home_locations.empty())
			continue;

		for (int offset = 1; offset < (int)G.agent_home_locations.size(); offset++)
		{
			int home = G.agent_home_locations[(original_index + offset) % G.agent_home_locations.size()];
			if (reserved_homes.find(home) != reserved_homes.end())
				continue;
			route_lengths[k] += travel_time(current_locations[k], home);
			current_locations[k] = home;
			reserved_homes.insert(home);
			break;
		}
	}

	long long fleet_time = 0;
	long long makespan = 0;
	for (double route_length : route_lengths)
	{
		long long time = (long long)std::ceil(route_length);
		fleet_time += time;
		makespan = std::max(makespan, time);
	}

	std::cout << "*** Estimate (no waiting, 1 cell/step) ***" << std::endl;
	double seconds_per_step = map_unit_distance / velocity;
	std::cout << "Estimated makespan time: " << makespan << " steps ("
		<< makespan * seconds_per_step << " s)" << std::endl;
	std::cout << "Estimated fleet total time: " << fleet_time << " steps ("
		<< fleet_time * seconds_per_step << " s)" << std::endl;
	std::cout << "Estimated fleet total distance: " << fleet_time << " units ("
		<< fleet_time * map_unit_distance << " m)" << std::endl;
}



void KivaSystem::update_goal_locations()
{
    if (!LRA_called)
        new_agents.clear();
	maintain_breakdown_goal();
	if (hold_endpoints)
	{
		unordered_map<int, int> held_locations; // <location, agent id>
		for (int k = 0; k < num_of_drives; k++)
		{
			int curr = paths[k][timestep].location; // current location
			if (goal_locations[k].empty())
			{
				int next = G.endpoints[rand() % (int)G.endpoints.size()];
				while (next == curr || held_endpoints.find(next) != held_endpoints.end())
				{
					next = G.endpoints[rand() % (int)G.endpoints.size()];
				}
				goal_locations[k].emplace_back(next, 0);
				held_endpoints.insert(next);
			}
			if (paths[k].back().location == goal_locations[k].back().first &&  // agent already has paths to its goal location
				paths[k].back().timestep >= goal_locations[k].back().second) // after its release time
			{
				int agent = k;
				int loc = goal_locations[k].back().first;
				auto it = held_locations.find(loc);
				while (it != held_locations.end()) // its start location has been held by another agent
				{
					int removed_agent = it->second;
					if (goal_locations[removed_agent].back().first != loc)
						cout << "BUG" << endl;
					new_agents.remove(removed_agent); // another agent cannot move to its new goal location
					cout << "Agent " << removed_agent << " has to wait for agent " << agent << " because of location " << loc << endl;
					held_locations[loc] = agent; // this agent has to keep holding this location
					agent = removed_agent;
					loc = paths[agent][timestep].location; // another agent's start location
					it = held_locations.find(loc);
				}
				held_locations[loc] = agent;
			}
			else // agent does not have paths to its goal location yet
			{
				if (held_locations.find(goal_locations[k].back().first) == held_locations.end()) // if the goal location has not been held by other agents
				{
					held_locations[goal_locations[k].back().first] = k; // hold this goal location
					new_agents.emplace_back(k); // replan paths for this agent later
					continue;
				}
				// the goal location has already been held by other agents 
				// so this agent has to keep holding its start location instead
				int agent = k;
				int loc = curr;
				cout << "Agent " << agent << " has to wait for agent " << held_locations[goal_locations[k].back().first] << " because of location " <<
					goal_locations[k].back().first << endl;
				auto it = held_locations.find(loc);
				while (it != held_locations.end()) // its start location has been held by another agent
				{
					int removed_agent = it->second;
					if (goal_locations[removed_agent].back().first != loc)
						cout << "BUG" << endl;
					new_agents.remove(removed_agent); // another agent cannot move to its new goal location
					cout << "Agent " << removed_agent << " has to wait for agent " << agent << " because of location " << loc << endl;
					held_locations[loc] = agent; // this agent has to keep holding its start location
					agent = removed_agent;
					loc = paths[agent][timestep].location; // another agent's start location
					it = held_locations.find(loc);
				}
				held_locations[loc] = agent;// this agent has to keep holding its start location
			}
		}
	}
	else
	{
		for (int k = 0; k < num_of_drives; k++)
		{
			if (breakdown_enabled() && breakdown_triggered && k == breakdown_agent)
				continue;
			int curr = paths[k][timestep].location; // current location
			if (useDummyPaths)
			{
				if (goal_locations[k].empty())
				{
					goal_locations[k].emplace_back(G.agent_home_locations[k], 0);
				}
				if (goal_locations[k].size() == 1)
				{
					int next;
					do {
						next = G.endpoints[rand() % (int)G.endpoints.size()];
					} while (next == curr);
					goal_locations[k].emplace(goal_locations[k].begin(), next, 0);
					new_agents.emplace_back(k);
				}
			}
			else
			{
				pair<int, int> goal; // The last goal location
				if (goal_locations[k].empty())
				{
					goal = make_pair(curr, 0);
				}
				else
				{
					goal = goal_locations[k].back();
				}
				double min_timesteps = G.get_Manhattan_distance(goal.first, curr); // G.heuristics.at(goal)[curr];
				while (min_timesteps <= simulation_window)
					// The agent might finish its tasks during the next planning horizon
				{
					// assign a new task
					pair<int, int> next;
					if (has_task_assignments())
					{
						if (!assign_next_task(k))
						{
							if (!final_return_assigned[k])
								assign_final_return_goal(k);
							break;
						}
						next = goal_locations[k].back();
					}
					else if (G.types[goal.first] == "Endpoint")
					{
						do
						{
							next = make_pair(G.endpoints[rand() % (int)G.endpoints.size()], 0);
						} while (next == goal);
						goal_locations[k].emplace_back(next);
					}
					else
					{
						std::cout << "ERROR in update_goal_function()" << std::endl;
						std::cout << "The fiducial type should not be " << G.types[curr] << std::endl;
						exit(-1);
					}
					min_timesteps += G.get_Manhattan_distance(next.first, goal.first); // G.heuristics.at(next)[goal];
					goal = next;
				}
			}
			}
		}

}


void KivaSystem::simulate(int simulation_time)
{
	std::cout << "*** Simulating " << seed << " ***" << std::endl;
	this->simulation_time = simulation_time;
	initialize();
	int consecutive_timeouts = 0;

	for (; timestep < simulation_time; timestep += simulation_window)
	{
		std::cout << "Timestep " << timestep << std::endl;
		bool planning_succeeded = true;

		update_start_locations();
		if (!final_return_phase)
		{
			update_goal_locations();
			start_final_return_phase_if_ready();
		}
		if (final_return_phase)
		{
			solver.hold_endpoints = true;
			planning_succeeded = solve_final_return();
		}
		else
		{
			solver.hold_endpoints = hold_endpoints || useDummyPaths;
			add_temporary_hold_goals();
			bool has_stationary_holds = false;
			for (int k = 0; k < num_of_drives; k++)
			{
				if (is_stationary_rest_agent(k))
				{
					has_stationary_holds = true;
					break;
				}
			}
			if (has_stationary_holds)
			{
				solver.hold_endpoints = false;
				planning_succeeded = solve_with_stationary_holds();
			}
			else
			{
				planning_succeeded = solve();
			}
			remove_temporary_hold_goals();
		}

		if (planning_succeeded)
		{
			consecutive_timeouts = 0;
		}
		else
		{
			consecutive_timeouts++;
			std::cout << "Planning failed at timestep " << timestep << " ("
				<< consecutive_timeouts << " consecutive failure";
			if (consecutive_timeouts != 1)
				std::cout << "s";
			std::cout << ")" << std::endl;
			if (max_consecutive_timeouts > 0 && consecutive_timeouts >= max_consecutive_timeouts)
			{
				std::cout << "ERROR: Reached max_consecutive_timeouts="
					<< max_consecutive_timeouts << ". Ending run as unsuccessful." << std::endl;
				execution_successful = false;
				break;
			}
		}

		// move drives
		auto new_finished_tasks = move();
		std::cout << new_finished_tasks.size() << " tasks has been finished" << std::endl;
		update_final_return_completion_by_position();

		// update tasks
		for (auto task : new_finished_tasks)
		{
			int id, loc, t;
			std::tie(id, loc, t) = task;
			finished_tasks[id].emplace_back(loc, t);
			if (breakdown_enabled() && breakdown_triggered &&
				id == breakdown_agent && loc == breakdown_location)
			{
				breakdown_arrived = true;
			}
			else if (has_task_assignments() && final_return_assigned[id] &&
				final_return_locations.size() > id && loc == final_return_locations[id])
			{
				final_return_completed[id] = true;
			}
			else
			{
				num_of_tasks++;
				update_breakdown_after_finished_goal(id);
			}
			if (hold_endpoints)
				held_endpoints.erase(loc);
		}

		if (congested())
		{
			cout << "***** Too many traffic jams ***" << endl;
			break;
		}
		if (has_task_assignments() && !has_remaining_task_assignments() && all_final_returns_completed())
		{
			timestep += simulation_window;
			break;
		}
	}

	update_start_locations();
	std::cout << std::endl << "Done!" << std::endl;
	print_summary();
	save_results();
}

void KivaSystem::print_summary() const
{
	int makespan_time = 0;
	long long fleet_total_time = 0;
	long long fleet_total_distance = 0;
	for (const auto& path : paths)
	{
		if (path.empty())
			continue;
		int last_timestep = 0;
		for (const auto& state : path)
		{
			if (state.location >= 0)
				last_timestep = std::max(last_timestep, state.timestep);
		}
		makespan_time = std::max(makespan_time, last_timestep);
		fleet_total_time += last_timestep;
		for (int t = 1; t < (int)path.size(); t++)
		{
			if (path[t - 1].location >= 0 && path[t].location >= 0 &&
				path[t - 1].location != path[t].location)
			{
				fleet_total_distance++;
			}
		}
	}

	std::cout << "*** Summary ***" << std::endl;
	std::cout << "Makespan time: " << makespan_time << std::endl;
	std::cout << "Fleet total time: " << fleet_total_time << std::endl;
	std::cout << "Fleet total distance: " << fleet_total_distance << std::endl;
}
