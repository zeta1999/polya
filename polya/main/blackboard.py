####################################################################################################
#
# blackboard.py
#
# Authors:
# Jeremy Avigad
# Rob Lewis
#
# The common data structure for sharing data between modules. An instance of Blackboard() keeps
# track of (sub)terms t0, t1, t2, t3, ... of interest, where by convention t0 represents one.
#
# When needed, we use IVar(i) to represent ti.
#
# The Blackboard class also stores the following information regarding its terms:
#
#  term_inequalities: inequalities of the form "ti comp c * tj", where c is nonzero
#  term_zero_inequalities: inequalities of the form "ti comp 0"
#  term_equalities: equalities of the form "ti = c * tj", where c is nonzero
#  term_zero_equalities: equalities of the form "ti = 0"
#  term_disequalities: disequalities of the form "ti != c * tj", where c is nonzero
#  term_zero_disequalities: disequalities of the form "ti != 0"
#
# These internal representations should be invisible to routines outside this module, which should
# only assert information and query information through class methods.
#
# To limit redundancy, there is a hierarchy of information stored.
#  * All known comparisons with zero are stored in zero_inequalities, zero_disequalities,
#    and zero_equalities.
#  * All known equalities between terms are stored in term_equalities.
#  * The two most relevant comparisons between t_i and t_j are stored in inequalities.
#    If one of these comparisons is an inequality with 0, it is duplicated here. If equality is
#    known between t_i and t_j, this is NOT stored here.
#  * All non-redundant disequalities between t_i and t_j are stored in disequalities. Anything that
#    is implied by known equality or inequality information is removed from this table.
#
#
####################################################################################################


#import random
import polya.main.terms as terms
import polya.main.messages as messages
import polya.util.geometry as geometry
import polya.util.mul_util as mul_util


class Error(Exception):
    pass


####################################################################################################
#
# Blackboard
#
####################################################################################################


class Tracker(object):
    """
    Allows modules to query for only the information that has been updated since the last time they
    were called.
    Modules will never interact directly with a Tracker.
    """

    def __init__(self, bb):
        self.m_index = 0
        self.updates = {}
        self.bb = bb

    def has_new_info(self, module):
        if module in self.updates:
            return len(self.updates[module]) > 0
        else:
            return True

    def get_new_info(self, module):
        if module in self.updates:
            s = self.updates[module]
            self.updates[module] = set()
            return s
        else:
            s = set(self.bb.inequalities.keys() + self.bb.disequalities.keys()
                    + self.bb.equalities.keys() + self.bb.zero_inequalities.keys()
                    + list(self.bb.zero_equalities.union(self.bb.zero_disequalities)))
            self.updates[module] = set()
            return s

    def identify(self):
        self.m_index += 1
        return self.m_index - 1

    def update(self, key):
        for k in self.updates:
            self.updates[k].add(key)


class Blackboard(object):

    def __init__(self):

        # named subterms
        self.num_terms = 1
        self.term_defs = {0: terms.one}       # maps each index to its definition
        self.terms = {0: terms.one}           # maps each index to its fully expanded term
        self.term_names = {terms.one.key: 0}      # reverse lookup: maps a term to is defining index

        # comparisons between named subterms
        self.inequalities = {}  # Dictionary mapping (i, j) to a list of Halfplanes [h1, h2],
                                # such that h2 is cw of h1
        self.zero_inequalities = {0: terms.GT}  # Dictionary mapping i to comp
        self.equalities = {}  # Dictionary mapping (i, j) to coeff
        self.zero_equalities = set([])  # Set of IVar indices equal to 0
        self.disequalities = {}  # Dictionary mapping (i, j) to a set of coeffs
        self.zero_disequalities = set([])  # Set of IVar indices not equal to 0

        self.clauses = set()  # List of Clauses
        #self.split = Split(seed=default_seed)  # This object determines how to perform case splits

        self.tracker = Tracker(self)

    def has_name(self, term):
        """
        Takes a Term.
        Returns True if term is syntactically equal to a term defined in the Blackboard, else False.
        """
        if term.key in self.term_names:
            return True, self.term_names[term.key]
        else:
            t = self.expand_term(term)
            if t.key in self.term_names:
                return True, self.term_names[t.key]
        return False, -1

    def expand_term(self, ti):
        """
        Expands a term with IVars into its full definition.
        """
        return ti.substitute({terms.IVar(i).key: self.terms[i] for i in range(self.num_terms)})

    def term_name(self, ti):
        """
        Assumes ti is a canonized term without IVars. Returns an IVar that represents t, if
        there is one. If not, recursively creates indices representing t and all its subterms, as
        needed.
        """
        t = self.expand_term(ti)
        if isinstance(t, terms.IVar):
            return t
        if t.key in self.term_names:
            return terms.IVar(self.term_names[t.key])
        else:
            if isinstance(t, terms.Var):
                new_def = t
            elif isinstance(t, terms.AddTerm):
                new_def = terms.AddTerm([terms.STerm(a.coeff, self.term_name(a.term))
                                         for a in t.args])
            elif isinstance(t, terms.MulTerm):
                new_def = terms.MulTerm([terms.MulPair(self.term_name(a.term), a.exponent)
                                         for a in t.args])
            elif isinstance(t, terms.FuncTerm):
                new_def = t.func(*[terms.STerm(a.coeff, self.term_name(a.term)) for a in t.args])
                #new_def = terms.FuncTerm(t.func_name, [terms.STerm(a.coeff, self.term_name(a.term))
                #                                        for a in t.args])
            else:
                print isinstance(t, terms.STerm)
                raise Error('cannot create name for {0!s}'.format(t))
            i = self.num_terms  # index of the new term
            self.term_defs[i] = new_def
            self.terms[i] = t
            self.term_names[t.key] = i
            self.num_terms += 1
            if messages.visible(messages.DEF):
                messages.announce_strong('Defining t{0!s} := {1!s}'.format(i, new_def))
            if messages.visible(messages.DEF_FULL):
                messages.announce_strong('  := {1!s}'.format(i, t))
            for j in self.zero_inequalities:
                hp = geometry.halfplane_of_comp(self.zero_inequalities[j], 0)
                self.inequalities[j, i] = [hp]
            return terms.IVar(i)

    def add_term(self, t):
        """
        Defines the term t, and any necessary subterms, without adding any comparison information.
        """
        self.term_name(t.canonize().term)

    def has_new_info(self, module):
        """
        Module is an int identifying a certain module.
        Returns True if new information has been learned since the last time that module asked.
        False otherwise.
        """
        return self.tracker.has_new_info(module)

    def get_new_info(self, module):
        """
        Module is an int identifying a certain module.
        Returns a list of indices i and pairs of indices (i, j) representing that information has
        been learned about those (pairs of) indices since the last time the module asked.
        """
        return self.tracker.get_new_info(module)

    def identify(self):
        """
        Returns a unique identifier for a module.
        """
        return self.tracker.identify()

    def get_inequalities(self):
        """
        Returns a list of comparisons t_i <> c*t_j or t_i <> 0.
        """
        inequalities = []
        for i in self.zero_inequalities:
            comp = self.zero_inequalities[i]
            inequalities.append(terms.comp_eval[comp](terms.IVar(i), 0))
        for (i, j) in self.inequalities:
            for hp in self.inequalities[i, j]:
                if hp.a != 0 and hp.b != 0:
                    inequalities.append(hp.to_comp(terms.IVar(i), terms.IVar(j)))
        return inequalities

    def get_equalities(self):
        """
        Returns a list of equalities t_i == c*t_j or ti == 0. Does not include definitional eqs.
        """
        equalities = [terms.IVar(i) == 0 for i in self.zero_equalities]
        for p in self.equalities:
            coeff = self.equalities[p]
            equalities.append(terms.IVar(p[0]) == coeff * terms.IVar(p[1]))
        return equalities

    def get_disequalities(self):
        """
        Returns a list of disequalities t_i != c*t_j or t_i != 0.
        """
        disequalities = [terms.IVar(i) != 0 for i in self.zero_disequalities]
        for p in self.disequalities:
            coeff_list = self.disequalities[p]
            for coeff in coeff_list:
                disequalities.append(terms.IVar(p[0]) != coeff * terms.IVar(p[1]))
        return disequalities

    def update_clause(self, *p):
        """
        p is either a singleton (i) or a pair (i, j).
        Updates any clauses that have literals containing either t_i or t_i and t_j.
        """
        for c in self.clauses:
            if len(p) == 1:
                c.update_on_index(p[0], self)
            else:
                c.update_on_indices(p[0], p[1], self)

        self.clauses = set(c for c in self.clauses if not c.satisfied)

        empty, unit = None, []
        for c in self.clauses:
            l = len(c)
            if l == 0:
                empty = c
                break
            elif l == 1:
                unit.append(c)
                #self.clauses.remove(c)

        if empty is not None:
            messages.announce('Contradiction from clause.', messages.DEBUG)
            self.raise_contradiction(100, terms.EQ, 100, 100)
        else:  # do these separately, so that learning from one won't recurse to the others.
            for c in unit:
                self.clauses.remove(c)

            for c in unit:
                tc = c.first()
                self.assert_comparison(tc)

    def implies(self, i, comp, coeff, j):
        """
        Checks to see if the statement ti comp coeff * tj is known by the Blackboard.
        """
        #print 'checking if t{0} {1} {2} t{3}'.format(i, terms.comp_str[comp], coeff, j)
        if coeff == 0:
            return self.implies_zero_comparison(i, comp)

        elif i == j:
            coeff1 = 1 - coeff
            if coeff1 > 0:
                return self.implies_zero_comparison(i, comp)
            elif coeff1 < 0:
                return self.implies_zero_comparison(i, terms.comp_reverse(comp))
            elif comp in [terms.GE, terms.LE, terms.EQ]:
                return True
            else:
                return False

        if comp in [terms.LT, terms.LE, terms.GE, terms.GT]:

            if j in self.zero_equalities:
                if i in self.zero_equalities:
                    return comp in [terms.LE, terms.GE]
                if i not in self.zero_inequalities:
                    return False
                comp1 = self.zero_inequalities[i]
                return ((comp1 == comp)
                        or (comp1 == terms.GT and comp == terms.GE)
                        or (comp1 == terms.LT and comp == terms.LE))

            elif i in self.zero_equalities:
                if j not in self.zero_inequalities:
                    return False
                comp1 = terms.comp_reverse(self.zero_inequalities[j])
                if coeff < 0:
                    comp1 = terms.comp_reverse(comp1)
                #print 'know 0 {0} tj, checking 0 {1} tj'.format(terms.comp_str[comp1], terms.comp_str[comp])
                return ((comp1 == comp)
                        or (comp1 == terms.GT and comp == terms.GE)
                        or (comp1 == terms.LT and comp == terms.LE))

            elif (i, j) in self.equalities:
                e_coeff = self.equalities[i, j]
                if coeff == e_coeff:
                    return comp in [terms.LE, terms.GE]
                pts = [(e_coeff, 1), (-e_coeff, -1)]
                pts = [p for p in pts if p[0]*self.sign(i) >= 0 and p[1]*self.sign(j) >= 0]
                return all(terms.comp_eval[comp](p[0], coeff * p[1]) for p in pts)

            #el
            else:

                new_comp = geometry.halfplane_of_comp(comp, coeff)
                old_comps = self.inequalities.get((i, j), [])

                for c in [d for d in old_comps if d.eq_dir(new_comp)]:
                    if c.strong or not new_comp.strong:
                        return True
                    else:
                        return False

                # If we reach here, then new_comp is not equidirectional with anything in old_comps
                if new_comp.strong:
                    n_comp = terms.GE if comp == terms.GT else terms.LE
                    if self.implies(i, n_comp, coeff, j) and \
                            not self.implies_zero_comparison(i, terms.NE) and \
                            not self.implies_zero_comparison(j, terms.NE) and \
                            not self.has_clause(terms.IVar(i) != 0, terms.IVar(j) != 0):
                        return False
                        # Only ruling out one point


                if len(old_comps) < 2:
                    return False
                if all(not o.strong for o in old_comps) and new_comp.strong:
                    return False
                return (new_comp.compare_hp(old_comps[0]) > 0
                        and old_comps[1].compare_hp(new_comp) > 0)
                # We know that b is clockwise from a.
                # If new_comp is cw from a, and b is cw from new_comp, then new_comp is redundant
                # If new_comp is cw from b, and a is cw from new_comp, then new_comp is contradict
                # If a and b are both cw from new_comp, take new_comp and b in that order.
                # If new_comp is cw from both a and b, take a and new_comp in that order.
                # recall that x.compare_hp(y) > 0 iff y is ccw of x.

        # All equality info is stored, so see if we know this equality.
        elif comp == terms.EQ:
            return coeff == self.equalities.get((i, j), None)  # or\
#                   (i in self.zero_equalities and j in self.zero_equalities)

        # See if we know this disequality, or if the disequality is implied by an inequality.
        elif comp == terms.NE:
            if coeff in self.disequalities.get((i, j), []):
                return True
            return self.implies(i, terms.GT, coeff, j) or self.implies(i, terms.LT, coeff, j)

    def implies_zero_comparison(self, i, comp):
        """
        Checks to see if the statement ti comp 0 is known by the Blackboard.
        """

        if i in self.zero_equalities:
            return comp in [terms.LE, terms.GE, terms.EQ]

        if comp in [terms.LT, terms.GT]:
            return self.zero_inequalities.get(i, terms.EQ) == comp

        elif comp == terms.LE:
            return self.zero_inequalities.get(i, terms.EQ) in [terms.LE, terms.LT] \
                or self.implies_zero_comparison(i, terms.EQ)

        elif comp == terms.GE:
            return self.zero_inequalities.get(i, terms.EQ) in [terms.GE, terms.GT] \
                or self.implies_zero_comparison(i, terms.EQ)

        elif comp == terms.EQ:
            return i in self.zero_equalities

        elif comp == terms.NE:
            if i in self.zero_disequalities:
                return True
            if i in self.zero_inequalities and self.zero_inequalities[i] in [terms.LT, terms.GT]:
                return True
            return False

    def implies_comparison(self, c):
        """
        Takes an instance of terms.TermComparison, and assume the comparison canonizes to
        a comparison between IVars. Determines whether the comparison is implied by
        information in the blackboard.
        """
        c = c.canonize()

        term1, comp, coeff, term2 = c.term1, c.comp, c.term2.coeff, c.term2.term
        if coeff == 0:
            term2 = terms.IVar(0)
        if isinstance(term1, terms.IVar) and isinstance(term2, terms.IVar):
            return self.implies(term1.index, comp, coeff, term2.index)
        else:
            return False

    def has_clause(self, *literals):
        disjunctions = []
        for l in literals:
            tc = l.canonize()
            i, j = self.term_name(tc.term1).index, self.term_name(tc.term2.term).index
            disjunctions.append((i, tc.comp, tc.term2.coeff, j))
        c = terms.Clause(disjunctions)

        c.update(self)

        return c in self.clauses

    def assert_comparison(self, c):
        """
        Take an instance of terms.TermComparison, and adds the comparison to the blackboard.
        If the comparison terms are not both IVars, finds or creates indices for the terms.
        """
        c = c.canonize()  # c is now of the form "term comp sterm"

        term1, comp, coeff, term2 = c.term1, c.comp, c.term2.coeff, c.term2.term
        if coeff == 0:
            term2 = terms.IVar(0)
        if not isinstance(term1, terms.IVar) or not isinstance(term2, terms.IVar):
            ivar1 = term1 if isinstance(term1, terms.IVar) else self.term_name(term1)
            ivar2 = term2 if isinstance(term2, terms.IVar) else self.term_name(term2)
            c = terms.TermComparison(ivar1, comp, coeff * ivar2).canonize()
            term1, comp, coeff, term2 = c.term1, c.comp, c.term2.coeff, c.term2.term
            if coeff == 0:
                term2 = terms.IVar(0)

        if self.implies(term1.index, comp, coeff, term2.index):
            return
        elif self.implies(term1.index, terms.comp_negate(comp), coeff, term2.index):
            self.raise_contradiction(term1.index, comp, coeff, term2.index)

        if comp in (terms.GE, terms.GT, terms.LE, terms.LT):
            if coeff == 0:
                self.assert_zero_inequality(term1.index, comp)
            else:
                self.assert_inequality(term1.index, comp, coeff, term2.index)
        elif comp == terms.EQ:
            if coeff == 0:
                self.assert_zero_equality(term1.index)
            else:
                self.assert_equality(term1.index, coeff, term2.index)
        elif comp == terms.NE:
            if coeff == 0:
                self.assert_zero_disequality(term1.index)
            else:
                self.assert_disequality(term1.index, coeff, term2.index)
        else:
            raise Error('Unrecognized comparison: {0!s}'.format())

    def add(self, *comparisons):
        """
        Asserts a list of comparisons.
        """
        for c in comparisons:
            self.assert_comparison(c)

    def assume(self, *comparisons):
        """
        Aliases add.
        """
        self.add(*comparisons)

    def assert_comparisons(self, *comparisons):
        """
        Aliases add.
        """
        self.add(*comparisons)

    def assert_inequality(self, i, comp, coeff, j):
        """
        Adds the inequality "ti comp coeff * tj".
        This should never be called directly; rather, assert_comparison should be used.
        """
        self.announce_comparison(i, comp, coeff, j)
        self.tracker.update((i, j))

        old_comps = self.inequalities.get((i, j), [])
        new_comp = geometry.halfplane_of_comp(comp, coeff)



        if i == 0 and comp in [terms.LE, terms.LT]:
            if coeff > 0:
                self.assert_zero_inequality(j, terms.GT)
            elif coeff < 0:
                self.assert_zero_inequality(j, terms.LT)
        for c in old_comps:
            if c.eq_dir(new_comp):
                if new_comp.strong and not c.strong:
                    c.strong = True
                    return
                else:
                    # shouldn't get here
                    return
                    #print old_comps
                    #print new_comp
                    #print i, j
                    #assert(False)
            elif c.opp_dir(new_comp):
                if (not new_comp.strong) and (not c.strong):
                    self.assert_comparison(terms.IVar(i) == coeff * terms.IVar(j))
                else:
                    assert(False)
                return
        #
        # if new_comp.strong:
        #     for c in old_comps:
        #         if c.eq_dir(new_comp):
        #             c.strong = True
        #             return


        # If we reach this point, we can assume that new_comp is not collinear with anything
        # in old_comps

        if new_comp.strong:
            w_comp = terms.GE if comp == terms.GT else terms.LE
            if self.implies(i, w_comp, coeff, j):
                # The only thing implied is not (ti = tj = 0).
                self.assert_clause(terms.IVar(i) != 0, terms.IVar(j) != 0)
                return

        if len(old_comps) == 0:
            new_comps = [new_comp]
        elif len(old_comps) == 1:
            old_comp = old_comps[0]
            k = old_comp.compare_hp(new_comp)
            if k < 0:
                # old_comp is ccw of new_comp
                new_comps = [old_comp, new_comp]
            elif k > 0:
                new_comps = [new_comp, old_comp]
            else:
                # we should never reach this point.
                assert(False)
        else:
            if new_comp.strong and self.implies(i, terms.comp_weaken(comp), coeff, j):
                self.assert_comparison(terms.IVar(i) != 0)
                self.assert_comparison(terms.IVar(j) != 0)
                return

            #a, b = old_comps[0], old_comps[1]
            # We know that b is clockwise from a.
            # If new_comp is cw from a, and b is cw from new_comp, then new_comp is redundant:
            #     this case is ruled out.
            # If new_comp is cw from b, and a is cw from new_comp, then new_comp is contradictory:
            #     also ruled out.
            # If a and b are both cw from new_comp, take new_comp and b in that order.
            # If new_comp is cw from both a and b, take a and new_comp in that order.
            # recall that x.compare_hp(y) > 0 iff y is ccw of x.
            if old_comps[0].compare_hp(new_comp) > 0 and old_comps[1].compare_hp(new_comp) > 0:
                new_comps = [new_comp, old_comps[1]]
            else:
                new_comps = [old_comps[0], new_comp]
            if new_comps[0].compare_hp(new_comps[1]) == 0:  # we have equality
                del self.inequalities[i, j]
                self.assert_equality(i, coeff, j)
                return None

        self.inequalities[i, j] = new_comps

        if (i, j) in self.disequalities:
            diseqs = self.disequalities.pop((i, j))
            n_diseqs = set(k for k in diseqs if not self.implies(i, terms.NE, k, j))
            if len(n_diseqs) > 0:
                self.disequalities[i, j] = n_diseqs

        self.update_clause(i, j)

    def assert_zero_inequality(self, i, comp):
        """
        Adds the inequality "ti comp 0".
        This should never be called directly; rather, assert_comparison should be used.
        """
        if i in self.zero_disequalities:
            c = terms.GT if comp in [terms.GE, terms.GT] else terms.LT
            self.zero_disequalities.remove(i)
            des = set(k for k in self.disequalities.get((0, i), set())
                      if not terms.comp_eval[c](k, 0))
            if len(des) > 0:
                self.disequalities[0, i] = des

        self.announce_zero_comparison(i, comp)
        self.tracker.update(i)

        if i in self.zero_inequalities:
            # We know that the new info is new and noncontradictory.
            if self.zero_inequalities[i] in [terms.LE, terms.GE] and comp in [terms.LE, terms.GE]:
                # learn equality
                del self.zero_inequalities[i]
                self.assert_zero_equality(i)
                return

        self.zero_inequalities[i] = comp
        new_zero_ineqs = []
        for j in (j for j in range(self.num_terms) if j != i):
            p = (i, j) if i < j else (j, i)
            old_comps = self.inequalities.get(p, [])
            if i < j:
                new_comp = geometry.halfplane_of_comp(comp, 0)
            else:
                new_comp = geometry.Halfplane((1 if comp in [terms.GE, terms.GT] else -1), 0,
                                              (True if comp in [terms.LT, terms.GT] else False))
            cont = False
            for c in old_comps:
                if c.eq_dir(new_comp) and c.strong is False and new_comp.strong is True:
                    c.strong = True
                    cont = True
            if cont:
                continue

            if len(old_comps) == 0:
                new_comps = [new_comp]
            elif len(old_comps) == 1:
                if old_comps[0].compare_hp(new_comp) > 0:  # old is cw of new
                    new_comps = [new_comp, old_comps[0]]
                else:
                    new_comps = [old_comps[0], new_comp]
            else:
                a_cw_n = old_comps[0].compare_hp(new_comp)
                b_cw_n = old_comps[1].compare_hp(new_comp)
                if a_cw_n > 0 and b_cw_n > 0:
                    new_comps = [new_comp, old_comps[1]]
                elif a_cw_n < 0 and b_cw_n < 0:
                    new_comps = [old_comps[0], new_comp]
                else:
                    new_comps = old_comps
            self.inequalities[p] = new_comps
            self.tracker.update(p)

            if self.sign(j) == 0 and len(self.inequalities[p]) == 2:
                j_g_0 = geometry.Halfplane(1, 0, True) if i < j else geometry.Halfplane(0, -1, True)
                cw_a = j_g_0.compare_hp(self.inequalities[p][0])
                cw_b = j_g_0.compare_hp(self.inequalities[p][1])
                strong = self.inequalities[p][0].strong and self.inequalities[p][1].strong
                if cw_a > 0 > cw_b:
                    if strong:
                        new_zero_ineqs.append(terms.IVar(j) > 0)
                    else:
                        new_zero_ineqs.append(terms.IVar(j) >= 0)
                elif cw_a < 0 < cw_b:
                    if strong:
                        new_zero_ineqs.append(terms.IVar(j) < 0)
                    else:
                        new_zero_ineqs.append(terms.IVar(j) < 0)
        for c in new_zero_ineqs:
            self.assert_comparison(c)

        self.update_clause(i)

    def assert_equality(self, i, coeff, j):
        """
        Adds the equality "ti = coeff * tj"
        This should never be called directly; rather, assert_comparison should be used.
        """
        self.equalities[i, j] = coeff
        if (i, j) in self.inequalities:
            self.inequalities.pop(i, j)
        if (i, j) in self.disequalities:
            self.disequalities.pop(i, j)
        self.announce_comparison(i, terms.EQ, coeff, j)
        self.tracker.update((i, j))
        self.update_clause(i, j)

    def assert_zero_equality(self, i):
        """
        Adds the equality "ti = 0"
        This should never be called directly; rather, assert_comparison should be used.
        """
        for k in self.zero_equalities:
            self.assert_comparison(terms.IVar(i) == terms.IVar(k))
        self.zero_equalities.add(i)
        # todo: there's a lot of simplification that could happen if a term is equal to 0
        self.announce_zero_comparison(i, terms.EQ)
        self.update_clause(i)
        self.tracker.update(i)

    def assert_disequality(self, i, coeff, j):
        """
        Adds the equality "ti != coeff * tj"
        This should never be called directly; rather, assert_comparison should be used.
        """
        # Print this now, in case the disequality is superseded; we want to see this first.
        self.announce_comparison(i, terms.NE, coeff, j)

        superseded = False
        if (i, j) in self.inequalities:
            for c in self.inequalities[i, j]:
                comp = c.to_comp(terms.IVar(i), terms.IVar(j))
                comp1, coeff1 = comp.comp, comp.term2.coeff
                if coeff1 == coeff:
                    if comp1 == terms.GE:
                        self.assert_inequality(i, terms.GT, coeff, j)
                        superseded = True
                    elif comp1 == terms.LE:
                        self.assert_inequality(i, terms.LT, coeff, j)
                        superseded = True

        if not superseded:
            if (i, j) in self.disequalities:
                if coeff not in self.disequalities[i, j]:
                    self.disequalities[i, j].add(coeff)
            else:
                self.disequalities[i, j] = {coeff}

            self.update_clause(i, j)
            self.tracker.update((i, j))

    def assert_zero_disequality(self, i):
        """
        Adds the equality "ti != 0"
        This should never be called directly; rather, assert_comparison should be used.
        """
        self.announce_zero_comparison(i, terms.NE)

        if i in self.zero_inequalities:
            comp = self.zero_inequalities[i]
            if comp == terms.LE:
                self.assert_zero_inequality(i, terms.LT)
            elif comp == terms.GE:
                self.assert_zero_inequality(i, terms.GT)
        else:
            self.zero_disequalities.add(i)

        self.update_clause(i)
        self.tracker.update(i)

    def assert_clause(self, *literals):
        """
        Takes a list of TermComparisons representing a disjunction.
        Stores the list as a Clause object.
        """
        #todo: ASSERTION_FULL version
        disjunctions = []
        for l in literals:
            tc = l.canonize()
            i, j = self.term_name(tc.term1).index, self.term_name(tc.term2.term).index
            disjunctions.append((i, tc.comp, tc.term2.coeff, j))
        c = terms.Clause(disjunctions)

        s = str(c)

        c.update(self)
        if c.satisfied:
            return

        if messages.visible(messages.ASSERTION) and c not in self.clauses:
            messages.announce_strong('Asserting clause: {0!s}'.format(s))
        l = len(c)
        if l > 1:
            self.clauses.add(c)
        elif l == 1:
            self.assert_comparison(c.first())
        else:
            messages.announce('Contradiction from clause.', messages.DEBUG)
            self.raise_contradiction(0, terms.EQ, 0, 0)

    def announce_comparison(self, i, comp, coeff, j):
        """
        Reports a successful assertion to the user.
        """
        if messages.visible(messages.ASSERTION):
            messages.announce_strong(
                'Asserting {0!s}'.format(terms.TermComparison(terms.IVar(i), comp,
                                                              coeff * terms.IVar(j))))
        if messages.visible(messages.ASSERTION_FULL):
            messages.announce_strong(
                '  := {0!s}'.format(terms.TermComparison(self.terms[i], comp,
                                                         coeff * self.terms[j])))

    def announce_zero_comparison(self, i, comp):
        """
        Reports a successful assertion to the user.
        """
        if messages.visible(messages.ASSERTION):
            messages.announce_strong(
                'Asserting {0!s}'.format(terms.TermComparison(terms.IVar(i), comp, terms.zero)))
        if messages.visible(messages.ASSERTION_FULL):
            messages.announce_strong(
                '  := {0!s}'.format(terms.TermComparison(self.terms[i], comp, terms.zero)))

    def raise_contradiction(self, i, comp, coeff, j):
        """
        Called when the given information contradicts something already known.
        """
        msg = 'Contradiction: {0!s}\n'.format(
            terms.TermComparison(terms.IVar(i), comp, coeff * terms.IVar(j)))
        msg += '  := {0!s}'.format(terms.TermComparison(self.terms[i], comp, coeff * self.terms[j]))
        raise terms.Contradiction(msg)

    def sign(self, i):
        """
        Returns 1 if ti > 0, -1 if ti < 0, 0 if = 0 or unknown
        """
        if i in self.zero_inequalities:
            comp = self.zero_inequalities[i]
            if comp == terms.GT:
                return 1
            elif comp == terms.LT:
                return -1
        return 0

    def weak_sign(self, i):
        """
        Returns 1 if ti >= 0, -1 if ti <= 0, 0 if = 0 or unknown
        """
        if i in self.zero_inequalities:
            comp = self.zero_inequalities[i]
            if comp in (terms.GT, terms.GE):
                return 1
            elif comp in (terms.LT, terms.LE):
                return -1
        return 0

    def info_dump(self):
        """
        For debugging purposes.
        Prints out all information known by the Blackboard.
        """
        st = '\n******\n'
        for i in self.term_defs:
            st += '{0!s} := {1!s}\n'.format(terms.IVar(i), self.term_defs[i])

        for i in self.zero_equalities:
            st += '{0!s} = 0\n'.format(terms.IVar(i))

        for i in self.zero_inequalities:
            st += '{0!s} {1!s} 0\n'.format(terms.IVar(i), terms.comp_str[self.zero_inequalities[i]])

        for i in self.zero_disequalities:
            st += '{0!s} != 0\n'.format(terms.IVar(i))

        for (i, j) in sorted(self.equalities.keys()):
            st += '{0!s} = {1!s}\n'.format(terms.IVar(i), self.equalities[i, j] * terms.IVar(j))

        for (i, j) in sorted(self.inequalities.keys()):
            for c in self.inequalities[i, j]:
                if c.a != 0 and c.b != 0:
                    st += str(c.to_comp(terms.IVar(i), terms.IVar(j))) + '\n'

        for (i, j) in sorted(self.disequalities.keys()):
            for val in self.disequalities[i, j]:
                st += '{0!s} != {1!s}\n'.format(terms.IVar(i), val * terms.IVar(j))

        st += '\n******\n'
        return st
    
    def get_halfplane_comparisons(self, i, j):
        """
        Assumes i ~= j, no equalities between ti and tj are known, and neither ti == 0 nor tj == 0
        are known.
        Returns a list of the at most two strongest half plane comparisons between ti and tj.
        """
    
        if i < j:
            hp_comps = self.inequalities.get((i, j), [])
        else:
            hp_comps = [geometry.halfplane_flip(hp) for hp in self.inequalities.get((j, i), [])]
    
        if i in self.zero_inequalities:
            comp = self.zero_inequalities[i]
            if comp in [terms.GT, terms.GE]:
                new_hp = geometry.Halfplane(0, -1, (True if comp == terms.GT else False))
            else:
                new_hp = geometry.Halfplane(0, 1, (True if comp == terms.LT else False))
            hp_comps = geometry.add_halfplane_comparison(new_hp, hp_comps)
    
        if j in self.zero_inequalities:
            comp = self.zero_inequalities[j]
            if comp in [terms.GT, terms.GE]:
                new_hp = geometry.Halfplane(-1, 0, (True if comp == terms.GT else False))
            else:
                new_hp = geometry.Halfplane(1, 0, (True if comp == terms.LT else False))
            hp_comps = geometry.add_halfplane_comparison(new_hp, hp_comps)
    
        return hp_comps
    
    def get_le_range(self, i, j):
        """
        Takes two indices, i, j < self,num_terms.
        Returns an geometry.ComparisonRange for the comparison t_i <= c * t_j.
        """

        si = self.sign(i)
        wsi = self.weak_sign(i)
        sj = self.sign(j)
        wsj = self.weak_sign(j)
    
        if i == j or (i < j and (i, j) in self.equalities) or (j < i and (j, i) in self.equalities):
            if i == j:
                coeff = geometry.Extended(1)
            elif i < j:
                coeff = geometry.Extended(self.equalities[i, j])
            else:
                coeff = geometry.Extended(1 / self.equalities[j, i])
            if sj == 1:
                return geometry.ComparisonRange(coeff, geometry.infty, False, True, True)
            elif wsj == 1:
                return geometry.ComparisonRange(coeff, geometry.infty, False, False, False)
            elif sj == -1:
                return geometry.ComparisonRange(geometry.neg_infty, coeff, True, True, False)
            elif wsj == -1:
                return geometry.ComparisonRange(geometry.neg_infty, coeff, False, False, False)
            else:
                return geometry.ComparisonRange(coeff, coeff, False, False, False)
    
        if j in self.zero_equalities:
            if i in self.zero_equalities:
                return geometry.ComparisonRange(geometry.neg_infty, geometry.infty,
                                                False, False, False)
            elif i in self.zero_inequalities:
                if self.zero_inequalities[i] == terms.LT:
                    return geometry.ComparisonRange(geometry.neg_infty, geometry.infty,
                                                    True, True, True)
                elif self.zero_inequalities[i] == terms.LE:
                    return geometry.ComparisonRange(geometry.neg_infty, geometry.infty,
                                                    False, False, False)
                else:
                    return geometry.empty_range
            else:
                return geometry.empty_range
    
        if i in self.zero_equalities:
            if j in self.zero_inequalities:
                comp = self.zero_inequalities[j]
                if comp == terms.GT:
                    return geometry.ComparisonRange(geometry.Extended(0), geometry.infty,
                                                    False, True, True)
                elif comp == terms.GE:
                    return geometry.ComparisonRange(geometry.Extended(0), geometry.infty,
                                                    False, False, False)
                elif comp == terms.LE:
                    return geometry.ComparisonRange(geometry.neg_infty, geometry.Extended(0),
                                                    False, False, False)
                else:
                    return geometry.ComparisonRange(geometry.neg_infty, geometry.Extended(0),
                                                    False, True, True)
            else:
                return geometry.empty_range
    
        hp_comps = self.get_halfplane_comparisons(i, j)
        if len(hp_comps) == 0:
            return geometry.empty_range
        if len(hp_comps) == 1:
            hp = hp_comps[0]
            if hp.b <= 0:
                return geometry.empty_range
            else:
                coeff = geometry.Extended(hp.a / hp.b)
                strict = hp.strong
                return geometry.ComparisonRange(coeff, coeff, strict, strict, strict)
        else:
            hp0, hp1 = hp_comps[0], hp_comps[1]
            interior_strong = (self.implies_zero_comparison(i, terms.NE) or
                               self.implies_zero_comparison(j, terms.NE))
            if hp0.compare_hp(hp1) == 1:
                hp0, hp1 = hp1, hp0
            if hp0.b <= 0 and hp1.b <= 0:
                return geometry.empty_range
            elif hp0.b <= 0:
                lower = geometry.neg_infty
                upper = geometry.Extended(hp1.a / hp1.b)
                return geometry.ComparisonRange(lower, upper, True, interior_strong, hp1.strong)
            elif hp1.b <= 0:
                lower = geometry.Extended(hp0.a / hp0.b)
                upper = geometry.infty
                return geometry.ComparisonRange(lower, upper, hp0.strong, interior_strong, True)
            else:
                lower = geometry.Extended(hp0.a / hp0.b)
                upper = geometry.Extended(hp1.a / hp1.b)
                return geometry.ComparisonRange(lower, upper,
                                                hp0.strong, interior_strong, hp1.strong)
    
    
    # TODO: this is similar to the previous one. Can they be combined?
    def get_ge_range(self, i, j):
        """
        Takes two indices, i, j < self,num_terms.
        Returns an geometry.ComparisonRange for the comparison t_i >= c * t_j.
        """

        si = self.sign(i)
        wsi = self.weak_sign(i)
        sj = self.sign(j)
        wsj = self.weak_sign(j)
    
        if i == j or (i < j and (i, j) in self.equalities) or (j < i and (j, i) in self.equalities):
            if i == j:
                coeff = geometry.Extended(1)
            elif i < j:
                coeff = geometry.Extended(self.equalities[i, j])
            else:
                coeff = geometry.Extended(1 / self.equalities[j, i])
            if sj == 1:
                return geometry.ComparisonRange(geometry.neg_infty, coeff, True, True, False)
            elif wsj == 1:
                return geometry.ComparisonRange(geometry.neg_infty, coeff, False, False, False)
            elif sj == -1:
                return geometry.ComparisonRange(coeff, geometry.infty, False, True, True)
            elif wsj == -1:
                return geometry.ComparisonRange(coeff, geometry.infty, False, False, False)
            else:
                return geometry.ComparisonRange(coeff, coeff, False, False, False)
    
        if j in self.zero_equalities:
            if i in self.zero_equalities:
                return geometry.ComparisonRange(geometry.neg_infty, geometry.infty,
                                                False, False, False)
            elif i in self.zero_inequalities:
                if self.zero_inequalities[i] == terms.GT:
                    return geometry.ComparisonRange(geometry.neg_infty, geometry.infty,
                                                    True, True, True)
                elif self.zero_inequalities[i] == terms.GE:
                    return geometry.ComparisonRange(geometry.neg_infty, geometry.infty,
                                                    False, False, False)
                else:
                    return geometry.empty_range
            else:
                return geometry.empty_range
    
        if i in self.zero_equalities:
            if j in self.zero_inequalities:
                comp = self.zero_inequalities[j]
                if comp == terms.GT:
                    return geometry.ComparisonRange(geometry.neg_infty, geometry.Extended(0),
                                                    True, True, False)
                elif comp == terms.GE:
                    return geometry.ComparisonRange(geometry.neg_infty, geometry.Extended(0),
                                                    False, False, False)
                elif comp == terms.LE:
                    return geometry.ComparisonRange(geometry.Extended(0), geometry.infty,
                                                    False, False, False)
                else:
                    return geometry.ComparisonRange(geometry.Extended(0), geometry.infty,
                                                    True, True, False)
            else:
                return geometry.empty_range
    
        hp_comps = self.get_halfplane_comparisons(i, j)
        if len(hp_comps) == 0:
            return geometry.empty_range
        if len(hp_comps) == 1:
            hp = hp_comps[0]
            if hp.b >= 0:
                return geometry.empty_range
            else:
                coeff = geometry.Extended(hp.a / hp.b)
                strict = hp.strong
                return geometry.ComparisonRange(coeff, coeff, strict, strict, strict)
        else:
            hp0, hp1 = hp_comps[0], hp_comps[1]
            interior_strong = (self.implies_zero_comparison(i, terms.NE) or
                               self.implies_zero_comparison(j, terms.NE))
            if hp0.compare_hp(hp1) == 1:
                hp0, hp1 = hp1, hp0
            if hp0.b >= 0 and hp1.b >= 0:
                return geometry.empty_range
            elif hp0.b >= 0:
                lower = geometry.neg_infty
                upper = geometry.Extended(hp1.a / hp1.b)
                return geometry.ComparisonRange(lower, upper, True, interior_strong, hp1.strong)
            elif hp1.b >= 0:
                lower = geometry.Extended(hp0.a / hp0.b)
                upper = geometry.infty
                return geometry.ComparisonRange(lower, upper, hp0.strong, interior_strong, True)
            else:
                lower = geometry.Extended(hp0.a / hp0.b)
                upper = geometry.Extended(hp1.a / hp1.b)
                return geometry.ComparisonRange(lower, upper,
                                                hp0.strong, interior_strong, hp1.strong)

    def le_coeff_range(self, i, j, coeff):
        """
        Takes a blackboard, B, and i, j < B.num_terms.
        Returns a comparison range for the relation c * ti <= coeff * tj, i.e. a range of values for
        c for which the comparison is known to hold.
        """

        if coeff == 0:
            if i in self.zero_equalities:
                return geometry.ComparisonRange(geometry.neg_infty, geometry.infty,
                                                False, False, False)
            elif i in self.zero_inequalities:
                if self.zero_inequalities[i] == terms.GT:
                    return geometry.ComparisonRange(geometry.neg_infty, geometry.infty,
                                                    True, True, True)
                elif self.zero_inequalities[i] == terms.GE:
                    return geometry.ComparisonRange(geometry.neg_infty, geometry.infty,
                                                    False, False, False)
                else:
                    return geometry.empty_range
            else:
                return geometry.empty_range
        elif coeff > 0:
            return self.get_ge_range(j, i).scale(coeff)
        else:  # coeff < 0
            return self.get_le_range(j, i).scale(coeff)
