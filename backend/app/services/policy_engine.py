from ortools.sat.python import cp_model

class PolicyEngine:
    @staticmethod
    def core_subject_ids(config, subjects) -> set[int]:
        """Which subjects count as 'core' is school configuration, never a hardcoded
        keyword list. Matching is by exact name, case-insensitive."""
        names = config.get("scheduling_policies", {}).get("core_subjects") or []
        wanted = {str(n).strip().lower() for n in names}
        return {s.id for s in subjects if s.name.strip().lower() in wanted}

    @staticmethod
    def adjacent_period_pairs(config, periods) -> list[tuple[int, int]]:
        """Consecutive period pairs that are genuinely back-to-back, i.e. safe to host a
        continuous double period. Two periods are adjacent only when they are numerically
        consecutive AND no break sits between them. A break is detected from
        `period_timings` when the earlier period's end time differs from the next period's
        start time (e.g. a lunch gap). With no timings configured, every numerically
        consecutive pair is treated as adjacent."""
        timings = config.get("period_timings") or []
        by_period: dict[int, tuple] = {}
        for t in timings:
            try:
                by_period[int(t["period"])] = (t.get("start"), t.get("end"))
            except (KeyError, ValueError, TypeError):
                continue
        pairs: list[tuple[int, int]] = []
        for i in range(len(periods) - 1):
            p, q = periods[i], periods[i + 1]
            if q != p + 1:
                continue
            tp, tq = by_period.get(p), by_period.get(q)
            if tp and tq and tp[1] and tq[0] and tp[1] != tq[0]:
                continue  # a break (lunch) separates them - not a valid double
            pairs.append((p, q))
        return pairs

    @staticmethod
    def double_period_requirements(config, subjects) -> dict[int, int]:
        """Map subject-id -> required number of continuous double periods per week, taken
        from `scheduling_policies.double_period_subjects` (a name -> count mapping).
        Names are matched case-insensitively; unknown names are ignored."""
        raw = config.get("scheduling_policies", {}).get("double_period_subjects") or {}
        wanted: dict[str, int] = {}
        for k, v in raw.items():
            try:
                wanted[str(k).strip().lower()] = int(v)
            except (ValueError, TypeError):
                continue
        out: dict[int, int] = {}
        for s in subjects:
            req = wanted.get(s.name.strip().lower())
            if req and req > 0:
                out[s.id] = req
        return out

    @staticmethod
    def apply_policies(model, x, y, config, days, periods, sections, subjects, activities,
                       teachers, resources_enabled, locked_core_by_sec_day=None,
                       locked_subject_by_sec_day=None):
        policies = config.get("scheduling_policies", {})
        
        # 1. max_consecutive_periods / break_after_n_periods
        max_consecutive = policies.get("max_consecutive_periods", 3)
        if max_consecutive and len(periods) > max_consecutive:
            for t in teachers:
                for d in days:
                    for start_idx in range(len(periods) - max_consecutive):
                         block_periods = periods[start_idx : start_idx + max_consecutive + 1]
                         terms = [x[k] for k in x if k[1] == d and k[2] in block_periods and k[4] == t.id]
                         if terms:
                             model.Add(sum(terms) <= max_consecutive)

        # 2. max_daily_periods
        max_daily = policies.get("max_daily_periods", 8)
        if max_daily:
            for t in teachers:
                for d in days:
                    terms = [x[k] for k in x if k[1] == d and k[4] == t.id]
                    if terms:
                        model.Add(sum(terms) <= max_daily)

        # 3. double_periods_allowed & subject_spread
        double_allowed = policies.get("double_periods_allowed", False)
        # Max lessons of one subject per section per day. Locked rows already occupy part of
        # that allowance, so they must be counted -- otherwise a locked lesson plus a solver
        # placed one silently exceeds the cap.
        spread_cap = 2 if double_allowed else 1
        locked_subj_day = locked_subject_by_sec_day or {}
        for sec in sections:
            for d in days:
                for subj in subjects:
                    terms = [x[k] for k in x if k[0] == sec.id and k[1] == d and k[3] == subj.id]
                    already = locked_subj_day.get((sec.id, d, subj.id), 0)
                    if terms:
                        model.Add(sum(terms) + already <= spread_cap)

        # 4. science_practical_consecutive
        science_consecutive = policies.get("science_practical_consecutive", False)
        if science_consecutive:
            for sec in sections:
                for d in days:
                    for subj in subjects:
                        # Identify science subjects
                        if "science" in subj.name.lower() or "practical" in subj.name.lower() or "lab" in subj.name.lower():
                            # For each period p, if p and p+2 are scheduled, p+1 must also be scheduled
                            for p_idx in range(len(periods) - 2):
                                p1 = periods[p_idx]
                                p2 = periods[p_idx + 1]
                                p3 = periods[p_idx + 2]
                                
                                term1 = sum(x[k] for k in x if k[0] == sec.id and k[1] == d and k[2] == p1 and k[3] == subj.id)
                                term2 = sum(x[k] for k in x if k[0] == sec.id and k[1] == d and k[2] == p2 and k[3] == subj.id)
                                term3 = sum(x[k] for k in x if k[0] == sec.id and k[1] == d and k[2] == p3 and k[3] == subj.id)
                                
                                model.Add(term1 + term3 - term2 <= 1)

        # 5. pet_last_periods (PE must be in the last 2 periods of the day)
        pet_last = policies.get("pet_last_periods", False)
        if pet_last and len(periods) >= 2:
            last_periods = periods[-2:]
            for k, var in x.items():
                # k = (sec_id, day, period, subj_id, teacher_id)
                subj = next((s for s in subjects if s.id == k[3]), None)
                if subj and ("pet" in subj.name.lower() or "physical education" in subj.name.lower()):
                    if k[2] not in last_periods:
                        model.Add(var == 0)
            for k, var in y.items():
                # k = (sec_id, day, period, activity_id)
                act = next((a for a in activities if a.id == k[3]), None)
                if act and ("pet" in act.name.lower() or "physical education" in act.name.lower()):
                    if k[2] not in last_periods:
                        model.Add(var == 0)

        # 6. Daily core-subject coverage: every class studies between min and max core
        #    periods each working day. Hard constraint. Core subjects come from config.
        core_ids = PolicyEngine.core_subject_ids(config, subjects)
        min_core = policies.get("min_core_per_day")
        max_core = policies.get("max_core_per_day")
        if core_ids and (min_core is not None or max_core is not None):
            locked_core = locked_core_by_sec_day or {}
            for sec in sections:
                for d in days:
                    terms = [x[k] for k in x if k[0] == sec.id and k[1] == d and k[3] in core_ids]
                    already = locked_core.get((sec.id, d), 0)
                    if min_core is not None:
                        model.Add(sum(terms) + already >= min_core)
                    if max_core is not None:
                        model.Add(sum(terms) + already <= max_core)

        # 7. Per-core-subject daily minimum: EVERY core subject appears at least N times
        #    on every working day, for every section. Hard constraint.
        core_daily_min = policies.get("core_subject_daily_min")
        if core_ids and core_daily_min:
            locked_subj = locked_subject_by_sec_day or {}
            for sec in sections:
                for d in days:
                    for subj_id in core_ids:
                        terms = [x[k] for k in x if k[0] == sec.id and k[1] == d and k[3] == subj_id]
                        already = locked_subj.get((sec.id, d, subj_id), 0)
                        model.Add(sum(terms) + already >= core_daily_min)

        # 8. Weekly class-teacher double period: on exactly one day of the week the class
        #    teacher takes both period 1 and period 2, teaching a subject already allocated
        #    to them. No special "class teacher period" is invented.
        if policies.get("class_teacher_double_period", False) and len(periods) >= 2:
            p_first, p_second = periods[0], periods[1]
            for sec in sections:
                ct_id = getattr(sec, "class_teacher_id", None)
                if not ct_id:
                    continue
                day_flags = []
                for d in days:
                    first = [x[k] for k in x if k[0] == sec.id and k[1] == d and k[2] == p_first and k[4] == ct_id]
                    second = [x[k] for k in x if k[0] == sec.id and k[1] == d and k[2] == p_second and k[4] == ct_id]
                    if not first or not second:
                        continue  # this day cannot host it
                    z = model.NewBoolVar(f"ct_double_s{sec.id}_d{d}")
                    model.Add(sum(first) >= 1).OnlyEnforceIf(z)
                    model.Add(sum(second) >= 1).OnlyEnforceIf(z)
                    day_flags.append(z)
                if day_flags:
                    model.Add(sum(day_flags) >= 1)
                else:
                    # No day can host it. The linter explains why; force infeasibility rather
                    # than silently dropping a hard constraint.
                    impossible = model.NewBoolVar(f"ct_double_impossible_s{sec.id}")
                    model.Add(impossible == 1)
                    model.Add(impossible == 0)

        # 9b. Continuous double-period requirements.
        #     scheduling_policies.double_period_subjects maps a subject name to the number of
        #     back-to-back (consecutive) same-day pairs it must form each week, in every
        #     section. Example: {"Tamil": 1, "Mathematics": 2}. A pair may never straddle a
        #     break such as lunch (adjacency comes from period_timings). "Twice a week" lands
        #     on two different days for free: the subject-spread cap already limits a subject
        #     to 2 lessons/day, so a day can host at most one of its doubles.
        dp_reqs = PolicyEngine.double_period_requirements(config, subjects)
        if dp_reqs:
            adj_set = set(PolicyEngine.adjacent_period_pairs(config, periods))
            for sec in sections:
                for subj_id, req in dp_reqs.items():
                    # Per-day variable lists for this subject in this section.
                    day_vars = {
                        d: {p: [x[k] for k in x
                                if k[0] == sec.id and k[1] == d and k[2] == p and k[3] == subj_id]
                            for p in periods}
                        for d in days
                    }

                    # (a) Any two same-day lessons of this subject must be a genuine
                    #     back-to-back pair: forbid every non-adjacent same-day combination.
                    #     Together with the spread cap this forces a 2-lesson day to be a
                    #     real double (and never more than 2).
                    for d in days:
                        for i, p in enumerate(periods):
                            for q in periods[i + 1:]:
                                if (p, q) in adj_set:
                                    continue
                                terms = day_vars[d][p] + day_vars[d][q]
                                if terms:
                                    model.Add(sum(terms) <= 1)

                    # (b) Require at least `req` days that carry a double. A day is a "double
                    #     day" exactly when the subject is scheduled twice there; by (a) those
                    #     two are guaranteed adjacent.
                    double_days = []
                    for d in days:
                        cnt_terms = [v for p in periods for v in day_vars[d][p]]
                        if not cnt_terms:
                            continue
                        dd = model.NewBoolVar(f"dbl_s{sec.id}_sub{subj_id}_d{d}")
                        model.Add(sum(cnt_terms) == 2).OnlyEnforceIf(dd)
                        model.Add(sum(cnt_terms) <= 1).OnlyEnforceIf(dd.Not())
                        double_days.append(dd)
                    if double_days:
                        model.Add(sum(double_days) >= req)

        # 9. morning_preference (soft constraint)
        morning_pref = policies.get("morning_preference", False)
        objective_terms = []
        if morning_pref:
            core_keywords = ["math", "science", "physics", "chemistry", "biology", "english", "history"]
            morning_periods = periods[:4]
            for k, var in x.items():
                subj = next((s for s in subjects if s.id == k[3]), None)
                if subj and k[2] in morning_periods:
                    if any(kw in subj.name.lower() for kw in core_keywords):
                        # Give a bonus of 2 for scheduling core subjects in morning
                        objective_terms.append(var * 2)

        return objective_terms
