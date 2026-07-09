#pragma once
#include "BasicSystem.h"
#include "KivaGraph.h"

class KivaSystem :
	public BasicSystem
{
public:
	KivaSystem(KivaGrid& G, MAPFSolver& solver);
	~KivaSystem();

	int breakdown_agent = -1;
	int breakdown_after_tasks = -1;
	int breakdown_location = -1;

	bool load_task_assignments(string fname);
	double loading_time = 0;
	void simulate(int simulation_time);


private:
	KivaGrid& G;
	unordered_set<int> held_endpoints;
	vector<list<pair<int, int> > > task_sequences; // pickup/dropoff goals per agent; extra lists are unassigned jobs
	vector<int> initial_start_locations;
	vector<int> final_return_locations;
	vector<bool> final_return_assigned;
	vector<bool> final_return_completed;
	vector<bool> temporary_hold_goal;
	bool final_return_phase = false;
	bool task_assignments_loaded = false;
	bool breakdown_triggered = false;
	bool breakdown_arrived = false;

	void initialize();
	void initialize_start_locations();
	void initialize_goal_locations();
	void update_goal_locations();
	bool breakdown_enabled() const;
	void validate_breakdown_config();
	void maintain_breakdown_goal();
	void trigger_breakdown();
	void requeue_breakdown_agent_goals();
	void update_breakdown_after_finished_goal(int agent);
	bool has_task_assignments() const;
	bool has_remaining_task_assignments() const;
	bool assign_next_task(int agent);
	void record_initial_start_locations();
	bool assign_final_return_goal(int agent);
	bool all_final_returns_assigned() const;
	bool all_final_returns_completed() const;
	void start_final_return_phase_if_ready();
	void update_final_return_completion_by_position();
	bool solve_final_return();
	bool is_stationary_rest_agent(int agent) const;
	int stationary_rest_location(int agent) const;
	bool solve_with_stationary_holds();
	void add_temporary_hold_goals();
	void remove_temporary_hold_goals();
	void print_estimate() const;
	void print_summary() const;
};
