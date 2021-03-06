####################################################################################################
#
# poly_add_module.py
#
# Authors:
# Jeremy Avigad
# Rob Lewis
#
# The routine for learning facts about additive terms using polytope projections.
# Much of the work is done in lrs_polyhedron_util.py, as it is shared with the multiplicative
# module.
#
# TODO:
#
####################################################################################################

import itertools

import polya.main.terms as terms
import polya.main.messages as messages
import polya.util.geometry as geo
import polya.modules.polyhedron.lrs_polyhedron_util as lrs_util
import polya.modules.polyhedron.lrs as lrs
import polya.util.timer as timer




####################################################################################################
#
# Internal classes
#
####################################################################################################

class VertexSetException(Exception):
    def __init__(self, s=''):
        self.message = s

####################################################################################################
#
# Helper functions for manipulating vertices
#
####################################################################################################


def get_boundary_vertices(vertices):
    """
    Takes a list of triples where the first two entries are (x,y) coordinates, and the third is
    delta.
    If all the vertices fall within the same semicircle, returns the pair that are at the extremes:
    the angle between these two vertices is greater than between any other pair.
    Otherwise, raises a VertexSetException.
    If any vertex on the boundary has nonzero delta coordinate, will return one of those.
    """

    if len(vertices) < 2:
        raise VertexSetException('Fewer than two vertices')

    b1 = next(v for v in vertices)
    l_b1 = geo.line_of_point(b1)

    try:
        b2 = next(v for v in vertices if not geo.are_collinear_rays(b1, v))
    except StopIteration:
        # All vertices point in the same direction.
        if any(v[2] != 0 for v in vertices):
            s = (b1[0], b1[1], 1)
        else:
            s = (b1[0], b1[1], 0)
        return s, s

    l_b2 = geo.line_of_point(b2)
    for v in vertices:
        l_v = geo.line_of_point(v)
        if geo.fall_on_same_side(l_v, [b1, b2]):
            if not geo.fall_on_same_side(l_b1, [v, b2]):
                b1, l_b1 = v, l_v
            elif not geo.fall_on_same_side(l_b2, [v, b1]):
                b2, l_b2 = v, l_v
            elif v[2] != 0:
                if geo.are_collinear_rays(b1, v):
                    b1, l_b1 = v, l_v
                elif geo.are_collinear_rays(b2, v):
                    b2, l_b2 = v, l_v

    if (not geo.fall_on_same_side(l_b1, vertices)) or (not geo.fall_on_same_side(l_b2, vertices)):
        raise VertexSetException('Points not in semicircle.')

    return b1, b2


####################################################################################################
#
# Main functions
#
####################################################################################################


def get_2d_comparisons(vertices, lin_set):
    """
    Takes a matrix of vertices. Each row is of the form
     [0, delta, c_0, ..., c_n]

    lin_set tracks the linear set for lrs.
    Returns all possible TermComparisons from the given vertices.
    """

    def adjust_strength(strong, comp):
        if strong:
            if comp == terms.GE:
                return terms.GT
            elif comp == terms.LE:
                return terms.LT
        else:
            if comp == terms.GT:
                return terms.GE
            elif comp == terms.LT:
                return terms.LE
        return comp

    if all(v[1] == 0 for v in vertices):  # We have a degenerate system.
        return [terms.IVar(0) == 0]

    learned_comparisons = []

    # Look for comparisons between t_i and t_j by checking each vertex.
    for (i, j) in itertools.combinations(range(len(vertices[0])-2), 2):
        #messages.announce(
            #'Looking for comparisons between {0} and {1}'.format(i, j), messages.DEBUG)

        i_j_vertices = set()
        weak = False
        for v in vertices:
            if v[i+2] != 0 or v[j+2] != 0:
                i_j_vertices.add((v[i+2], v[j+2], v[1]))
            elif v[1] != 0:
                #(c,0,0) is a vertex, so (c-epsilon,0,0) is reachable.
                weak = True

        for k in lin_set:
            v = vertices[k]
            if v[i+2] != 0 or v[j+2] != 0:
                i_j_vertices.add((-v[i+2], -v[j+2], v[1]))

        if (i, j) == (2, 4): messages.announce('vertices:'+str(i_j_vertices), messages.DEBUG)

        if len(i_j_vertices) == 0:
            learned_comparisons.extend([terms.IVar(i) == 0, terms.IVar(j) == 0])
            continue

        # Find the extremal vertices.
        try:
            bound1, bound2 = get_boundary_vertices(i_j_vertices)
            #messages.announce('boundary vertices:'+str(bound1)+', '+str(bound2), messages.DEBUG)
        except VertexSetException:  # Nothing we can learn for this i, j pair.
            continue

        # Now, all vertices lie in the same halfplane between bound1 and bound2.
        strong1, strong2 = (not weak) and (bound1[2] == 0), (not weak) and (bound2[2] == 0)
        l_b1, l_b2 = geo.line_of_point(bound1), geo.line_of_point(bound2)

        if l_b1 == l_b2:
            if bound1[0]*bound2[0] >= 0 and bound1[1]*bound2[1] >= 0:
                # the rays are collinear. Learn equality.
                learned_comparisons.append(bound1[1] * terms.IVar(i) == bound1[0] * terms.IVar(j))
                if strong1 or strong2:
                    learned_comparisons.append(
                        bound1[1] * terms.IVar(i) < bound1[0] * terms.IVar(j)
                    )

            else:
                #the rays are opposite. Figure out the comparison direction another way.
                try:
                    pt = next(v for v in i_j_vertices if not l_b1.get_direction(v) == terms.EQ)
                    dir1 = adjust_strength(strong1 and strong2, l_b1.get_direction(pt))
                    learned_comparisons.append(
                        terms.comp_eval[dir1](bound1[1] * terms.IVar(i), bound1[0] * terms.IVar(j))
                    )
                except StopIteration:
                    # There is no direction information to be found: all vertices are collinear.
                    #continue
                    learned_comparisons.append(bound1[1]*terms.IVar(i) == bound1[0]*terms.IVar(j))
                #print '*** l_b1 = ', l_b1, pt, terms.comp_str[l_b1.get_direction(pt)]

        else:
            # Otherwise, the points do not lie on the same line through the origin.
            dir1 = adjust_strength(strong1, l_b1.get_direction(bound2))
            dir2 = adjust_strength(strong2, l_b2.get_direction(bound1))
            learned_comparisons.append(
                terms.comp_eval[dir1](bound1[1] * terms.IVar(i), bound1[0] * terms.IVar(j))
            )
            learned_comparisons.append(
                terms.comp_eval[dir2](bound2[1] * terms.IVar(i), bound2[0] * terms.IVar(j))
            )
        #messages.announce('Learned:'+str(learned_comparisons), messages.DEBUG)
    return learned_comparisons


def get_additive_information(B):
    """
    Retrieves the relevant information from the blackboard.
    """
    comparisons = B.get_inequalities() + B.get_equalities()

    for key in B.term_defs:
        if isinstance(B.term_defs[key], terms.AddTerm):
            comparisons.append(
                terms.TermComparison(B.term_defs[key], terms.EQ, terms.IVar(key))
            )

    return comparisons


class PolyAdditionModule:
    def __init__(self):
        if not lrs.lrs_path:
            raise Exception('lrs is needed to instantiate a polyhedron module.')

    def update_blackboard(self, B):
        """
        Saturates a Blackboard B with additive inferences.
        """
        timer.start(timer.PADD)
        messages.announce_module('polyhedron additive module')

    #    learn_additive_sign_info(blackboard)

        comparisons = get_additive_information(B)

        h_matrix = lrs_util.create_h_format_matrix(comparisons, B.num_terms)
        messages.announce('Halfplane matrix:', messages.DEBUG)
        messages.announce(h_matrix, messages.DEBUG)
        v_matrix, v_lin_set = lrs_util.get_vertices(h_matrix)
        messages.announce('Vertex matrix:', messages.DEBUG)
        #messages.announce(str(v_matrix), messages.DEBUG)
        for l in v_matrix:
            messages.announce(str(l), messages.DEBUG)
        messages.announce('Linear set:', messages.DEBUG)
        messages.announce(str(v_lin_set), messages.DEBUG)

        new_comparisons = get_2d_comparisons(v_matrix, v_lin_set)

        for c in new_comparisons:
            B.assert_comparison(c)

        timer.stop(timer.PADD)

    def get_split_weight(self, B):
        return None


####################################################################################################
#
# Tests
#
####################################################################################################


if __name__ == '__main__':

    # # can change 'normal' to 'quiet' or 'low'
    # messages.set_verbosity(messages.normal)
    #
    # u, v, w, x, y, z = terms.Vars('u, v, w, x, y, z')
    # f = terms.Func('f')
    # g = terms.Func('g')
    #
    # B = blackboard.Blackboard()
    #
    # B.assert_comparison(u > 0)
    # B.assert_comparison(u < 1)
    # B.assert_comparison(v > 0)
    # B.assert_comparison(v < 1)
    # B.assert_comparison(u + v > u * v)
    #
    # p = PolyAdditionModule()
    #
    # p.update_blackboard(B)
    pass
