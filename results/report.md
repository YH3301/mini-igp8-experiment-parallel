# Mini-IGP8 status

- Run: **78cf9bf6202f**
- Catalogue: **93 / 157 pairs** across **39 / 50 groups**
- Current frozen-benchmark score: **14070.754**
- Search candidates checked: **57988**
- Search candidates since new pair/solver change: **5000**
- Accepted solver generations: **2**
- Best-field-discriminant improvements: **112**
- Last stop: `completed`

## Complete solver experiment history

This table is intentionally append-only. Earlier rows are never hidden or deleted when a solver is accepted.

| Gen | Candidate | Accepted | Stage | Screen | Benchmark | Fresh pairs | Seed hits | Disc improvements | Reason | Hypothesis |
|---:|---|---|---|---:|---:|---:|---:|---:|---|---|
| 0 | incumbent | yes | baseline |  | 4010.974000000000 |  |  |  | `baseline_measured` | uniform small-coefficient random monic octics |
| 1 | A | no | final_round1_pruned | 5051.000000000000 | 7071.000000000000 | 7 | 20 |  | `final_round1_pruned` | Generic irreducible compositions g(q(x)), with g a monic quartic and q a monic quadratic, and Q(h(x)), with Q a monic quadratic and h a monic quartic, will land in proper wreath-product subgroups rather than 8T50. The two orientations realize inequivalent degree-8 block systems and should therefore expose at least two regions of the missing-group catalogue. |
| 1 | B | no | screen_pruned | 1010.998000000000 |  |  |  |  | `screen_pruned_to_top_survivors` | Small nonsymmetric perturbations of monic products of eight separated integral linear factors remain totally real, while generically destroying the split polynomial's special structure and producing full S8 fields. |
| 1 | C | no | screen_pruned | 1011.000000000000 |  |  |  |  | `screen_pruned_to_top_survivors` | Octics defined by f'(x)=8xq(x)^2 and f(0)=s^2 have square discriminant and no real roots. Generic irreducible members should therefore have Galois group A8, namely 8T49, and signature r=0. |
| 1 | D | no | final_round1_pruned | 9040.995999999999 | 16070.994000000001 | 9 | 20 |  | `final_round1_pruned` | Low-height Eisenstein octics with trace normalization and mixed sparse/dense coefficient shapes will preserve the incumbent's broad S8 behavior while eliminating most reducible waste and improving the very large 8T50 discriminant records, especially at r=0,4,6. |
| 1 | E | no | final_rejected | 25100.936000000002 | 30150.955000000002 | 35 | 60 | 3 | `final_lower_rank` | A counter-interleaved portfolio of reciprocal lifts, Dickson/Chebyshev-type octics, iterated quadratic maps, and lacunary trinomials will cover several unrelated proper-subgroup mechanisms; no single family needs to dominate for the portfolio to discover missing groups. |
| 1 | S | yes | final | 30160.867999999999 | 49250.843000000001 | 63 | 60 | 4 | `accepted_discovery_gain` | Build one geometry-driven portfolio organized by forced permutation structure, not by finalist identity. The fresh results favor E for discovery (31 new pairs, 17 groups), while A contributes clean block-system coverage and D supplies guaranteed irreducibility plus a discriminant-oriented control lane. Merge overlapping reciprocal and quartic-after-quadratic constructions into one size-2-block superfamily, then interleave that with size-4 blocks, nested binary actions, dihedral fibers, sparse exceptional loci, and low-height Eisenstein polynomials. |
| 2 | A | no | final_rejected | 6030.822000000000 | 6030.611000000000 | 2 | 58 | 0 | `final_lower_rank` | Let c(t) be a seed-enumerated irreducible cubic with roots alpha_1, alpha_2, alpha_3, set d_i=q(alpha_i) for a low-degree integer q, and form the octic whose roots are epsilon_1 sqrt(d_1)+epsilon_2 sqrt(d_2)+epsilon_3 sqrt(d_3) for all sign triples. Generic specializations have a transitive subgroup of C2 wr S3 acting on eight cube vertices, while square-class relations, cubic discriminant conditions, and controlled degenerations traverse several proper subgroups. This geometry should preferentially reach entirely absent catalogue groups rather than the incumbent’s common size-2 or size-4 block populations. |
| 2 | B | no | screen_pruned | 30140.781999999999 |  |  |  |  | `screen_pruned_to_top_survivors` | For composition and reciprocal covers, the real-root count is governed by the position of real base roots relative to explicit branch thresholds. Constructing parameters in certified chambers for r=0,2,4,6,8 should preserve the relevant imprimitive Galois geometry while filling signatures that blind coefficient sampling almost never visits, notably the many missing totally real cases and the r=4 gaps in otherwise well-covered groups. |
| 2 | C | no | screen_pruned | 2020.984000000000 |  |  |  |  | `screen_pruned_to_top_survivors` | For seed-enumerated integral elliptic curves E:y^2=x^3+Ax+B, eliminate x between the 3-division polynomial and z=y+kx. The resulting degree-8 polynomial has roots indexed by the eight nonzero 3-torsion points and generically realizes the transitive GL(2,3) action, with special mod-3 images producing proper transitive subgroups. This primitive eight-point geometry is unrelated to compositions, reciprocal pairs, iterated quadratics, or Dickson covers. |
| 2 | D | no | preliminary_rejected | 36200.824000000001 | 47260.756999999998 | 2 | 2 |  | `rejected_seed_consistency_regression` | Much of the incumbent’s value comes from its geometry, but some deformations erase that geometry—for example, adding an arbitrary linear term to a Dickson polynomial—and the reciprocal and general size-2 lanes spend retries in overlapping regions. A repaired portfolio that only uses invariant-preserving deformations, allocates overlap once, and screens locally within each geometry should yield more proper-subgroup hits and more low-discriminant records per slot. |
| 2 | E | no | final_round1_pruned | 10050.798000000001 | 12060.750000000000 | 2 | 15 |  | `final_round1_pruned` | If alpha has degree four, beta has degree two, and the fields are suitably disjoint, theta=alpha+beta has degree eight and its conjugates form a 4-by-2 Cartesian product. The polynomial Res_y(q(y),f(x-y)) therefore realizes constrained product subgroups rather than the full wreath groups favored by polynomial composition. Varying the quartic Galois geometry and the signatures of both factors should expose additional missing groups and signatures, while the discriminant behavior of a compositum of small-discriminant factors offers unusually strong secondary record potential. |
| 2 | S | yes | final | 14070.809999999999 | 14070.754000000001 | 5 | 60 | 0 | `accepted_discovery_gain` | Use a single orbit-polynomial engine with two complementary degree-eight geometries: signed-cube orbits for high-value access to rare C2^3⋊G subgroups, and quadratic–quartic Cartesian orbits for broader, high-yield coverage of G4×C2 groups. The fresh results justify favoring the cube branch for discovery (3 new pairs and 102 fresh-pair hits versus 2 and 63), while retaining the compositum branch because it verified more reliably (86.7% versus 76.4%) and covered twice as many groups. Coherence comes from one scheduler, canonicalization layer, irreducibility sieve, signature balancer, and Pareto selector—not from concatenating the two finalist programs. |

## Catalogue

| Group | r | Field discriminant | First solver | Best solver | Coefficients |
|---|---:|---:|---|---|---|
| 8T1 | 0 | 2147483648 | `6746e8cd7253` | `6746e8cd7253` | `2, 0, 16, 0, 20, 0, 8, 0, 1` |
| 8T1 | 8 | 2147483648 | `6746e8cd7253` | `6746e8cd7253` | `2, 0, -16, 0, 20, 0, -8, 0, 1` |
| 8T2 | 0 | 1265625 | `6746e8cd7253` | `6746e8cd7253` | `1, -1, 0, 1, -1, 1, 0, -1, 1` |
| 8T2 | 8 | 1358954496 | `6746e8cd7253` | `6746e8cd7253` | `-2, -8, 12, 24, -30, -8, 20, -8, 1` |
| 8T3 | 0 | 5308416 | `6746e8cd7253` | `6746e8cd7253` | `1, 0, 0, 0, -1, 0, 0, 0, 1` |
| 8T3 | 8 | 12745506816 | `26be6d9b6a4a` | `26be6d9b6a4a` | `-188, -1376, 856, 1024, -672, -16, 76, -16, 1` |
| 8T4 | 0 | 40960000 | `6746e8cd7253` | `6746e8cd7253` | `1, 0, 0, 0, 3, 0, 0, 0, 1` |
| 8T4 | 8 | 9475854336 | `26be6d9b6a4a` | `26be6d9b6a4a` | `9, 0, -90, 0, 115, 0, -22, 0, 1` |
| 8T6 | 0 | 4102893 | `6746e8cd7253` | `6746e8cd7253` | `1, -1, 5, -6, 11, -6, 5, -1, 1` |
| 8T6 | 2 | 4286875 | `6746e8cd7253` | `6746e8cd7253` | `1, -3, 1, -8, -1, -8, 1, -3, 1` |
| 8T6 | 8 | 5156108238848 | `6746e8cd7253` | `6746e8cd7253` | `8, 0, -128, 0, 80, 0, -16, 0, 1` |
| 8T8 | 2 | 268435456 | `6746e8cd7253` | `6746e8cd7253` | `-1, 0, 0, 0, -2, 0, 0, 0, 1` |
| 8T9 | 0 | 3504384 | `6746e8cd7253` | `6746e8cd7253` | `1, 0, -3, 0, 2, 0, 0, 0, 1` |
| 8T9 | 4 | 40960000 | `6746e8cd7253` | `6746e8cd7253` | `1, 0, -6, 0, 7, 0, -4, 0, 1` |
| 8T9 | 8 | 1467470577664 | `26be6d9b6a4a` | `26be6d9b6a4a` | `-153, 120, 626, -140, -413, -92, 30, 12, 1` |
| 8T10 | 0 | 4000000 | `6746e8cd7253` | `6746e8cd7253` | `11, 46, 99, 132, 119, 74, 31, 8, 1` |
| 8T11 | 0 | 5308416 | `6746e8cd7253` | `6746e8cd7253` | `1, 0, -4, 0, 5, 0, -2, 0, 1` |
| 8T11 | 4 | 23040000 | `6746e8cd7253` | `6746e8cd7253` | `1, 12, 28, 32, 13, -8, -8, 0, 1` |
| 8T11 | 8 | 38813099360256 | `6746e8cd7253` | `6746e8cd7253` | `25, 0, -128, 0, 80, 0, -16, 0, 1` |
| 8T13 | 0 | 39337984 | `26be6d9b6a4a` | `26be6d9b6a4a` | `1369, 0, -84, 0, 78, 0, -4, 0, 1` |
| 8T13 | 8 | 73116160000 | `26be6d9b6a4a` | `26be6d9b6a4a` | `1, 0, -348, 0, 198, 0, -28, 0, 1` |
| 8T14 | 0 | 136048896 | `6746e8cd7253` | `6746e8cd7253` | `1, 2, 4, -2, 2, -2, 4, 2, 1` |
| 8T14 | 8 | 13969863066384 | `26be6d9b6a4a` | `26be6d9b6a4a` | `441, 0, -11628, 0, 3886, 0, -124, 0, 1` |
| 8T15 | 0 | 143327232 | `6746e8cd7253` | `6746e8cd7253` | `3, 0, 0, 0, -3, 0, 0, 0, 1` |
| 8T15 | 2 | 40960000 | `6746e8cd7253` | `6746e8cd7253` | `-1, 0, 2, 0, 5, 0, 4, 0, 1` |
| 8T15 | 4 | 14670139392 | `6746e8cd7253` | `6746e8cd7253` | `1, 2, -5, -4, -5, -4, -5, 2, 1` |
| 8T15 | 8 | 249362220897533952 | `6746e8cd7253` | `6746e8cd7253` | `13, 0, -128, 0, 80, 0, -16, 0, 1` |
| 8T16 | 0 | 20000000 | `6746e8cd7253` | `6746e8cd7253` | `1, 2, 3, 4, 5, -26, 23, -8, 1` |
| 8T16 | 4 | 2147483648 | `6746e8cd7253` | `6746e8cd7253` | `2, 0, 0, 0, -4, 0, 0, 0, 1` |
| 8T17 | 0 | 1257728 | `6746e8cd7253` | `6746e8cd7253` | `1, 0, 5, -2, 9, -2, 5, 0, 1` |
| 8T18 | 0 | 9144576 | `6746e8cd7253` | `6746e8cd7253` | `1, 0, 2, 0, 0, 0, -1, 0, 1` |
| 8T18 | 4 | 19360000 | `6746e8cd7253` | `6746e8cd7253` | `1, 0, -9, 0, 12, 0, -6, 0, 1` |
| 8T18 | 8 | 18604960000 | `6746e8cd7253` | `6746e8cd7253` | `1, 0, -15, 0, 28, 0, -10, 0, 1` |
| 8T19 | 0 | 67108864 | `6746e8cd7253` | `6746e8cd7253` | `1, 0, 0, 0, 4, 0, -4, 0, 1` |
| 8T20 | 4 | 268435456 | `6746e8cd7253` | `6746e8cd7253` | `-2, 0, 16, 32, 16, -8, -8, 0, 1` |
| 8T21 | 0 | 33554432 | `6746e8cd7253` | `6746e8cd7253` | `9, 0, -8, 8, 14, -32, 24, -8, 1` |
| 8T22 | 0 | 51840000 | `6746e8cd7253` | `6746e8cd7253` | `19, 58, 109, 136, 120, 74, 31, 8, 1` |
| 8T22 | 4 | 815712436224 | `6746e8cd7253` | `6746e8cd7253` | `4, 0, 0, 0, -10, 0, 0, 0, 1` |
| 8T23 | 2 | 22665187 | `6746e8cd7253` | `6746e8cd7253` | `1, -12, 28, -39, 38, -25, 13, -4, 1` |
| 8T24 | 0 | 1763584 | `6746e8cd7253` | `6746e8cd7253` | `1, 0, 1, -2, 1, -2, 1, 0, 1` |
| 8T24 | 4 | 184090624 | `6746e8cd7253` | `6746e8cd7253` | `1, 0, 0, 0, -1, 0, -2, 0, 1` |
| 8T24 | 8 | 89865650176 | `6746e8cd7253` | `6746e8cd7253` | `-1, 8, 32, -20, -49, -4, 18, 8, 1` |
| 8T26 | 0 | 78675968 | `6746e8cd7253` | `6746e8cd7253` | `23, 86, 163, 192, 154, 86, 33, 8, 1` |
| 8T26 | 2 | 163840000 | `6746e8cd7253` | `6746e8cd7253` | `-4, 0, -4, 0, 2, 0, 4, 0, 1` |
| 8T26 | 4 | 43789058048 | `6746e8cd7253` | `6746e8cd7253` | `2, 0, 0, 0, -5, 0, 0, 0, 1` |
| 8T27 | 0 | 5328125 | `6746e8cd7253` | `6746e8cd7253` | `1, -1, 5, -4, 9, -4, 5, -1, 1` |
| 8T27 | 2 | 196171875 | `6746e8cd7253` | `6746e8cd7253` | `1, 3, 3, 6, 5, 6, 3, 3, 1` |
| 8T27 | 6 | 1073741824 | `6746e8cd7253` | `6746e8cd7253` | `-1, 0, 4, 0, 2, 0, -4, 0, 1` |
| 8T27 | 8 | 2841328125 | `6746e8cd7253` | `6746e8cd7253` | `1, 12, -32, -51, 50, 99, 53, 12, 1` |
| 8T28 | 0 | 90870848 | `6746e8cd7253` | `6746e8cd7253` | `1, -3, 5, -5, 6, -5, 5, -3, 1` |
| 8T28 | 4 | 288800000 | `6746e8cd7253` | `6746e8cd7253` | `5, 0, -15, 0, 14, 0, -6, 0, 1` |
| 8T28 | 8 | 9697230848 | `6746e8cd7253` | `6746e8cd7253` | `8, -64, -48, 288, 60, -208, 92, -16, 1` |
| 8T29 | 0 | 3504384 | `6746e8cd7253` | `6746e8cd7253` | `1, 0, 1, 0, 2, 0, 2, 0, 1` |
| 8T29 | 4 | 134560000 | `6746e8cd7253` | `6746e8cd7253` | `1, 0, 3, 0, -2, 0, -2, 0, 1` |
| 8T30 | 0 | 184146722816 | `6746e8cd7253` | `6746e8cd7253` | `14, 0, 16, 0, 12, 0, 4, 0, 1` |
| 8T30 | 2 | 21434375 | `6746e8cd7253` | `6746e8cd7253` | `1, -1, 2, -5, 1, -5, 2, -1, 1` |
| 8T31 | 0 | 17668125 | `6746e8cd7253` | `6746e8cd7253` | `31, -153, 339, -435, 356, -189, 63, -12, 1` |
| 8T31 | 2 | 2717908992 | `6746e8cd7253` | `6746e8cd7253` | `-2, 0, -4, 0, 2, 0, 4, 0, 1` |
| 8T31 | 6 | 2717908992 | `6746e8cd7253` | `6746e8cd7253` | `-2, 0, 4, 0, 2, 0, -4, 0, 1` |
| 8T31 | 8 | 20316160000 | `6746e8cd7253` | `6746e8cd7253` | `31, 0, -72, 0, 48, 0, -12, 0, 1` |
| 8T32 | 0 | 1142440000 | `6746e8cd7253` | `6746e8cd7253` | `1, 6, 15, -4, -5, 20, 22, 8, 1` |
| 8T35 | 0 | 1820637 | `6746e8cd7253` | `6746e8cd7253` | `1, -1, 3, -2, 5, -2, 3, -1, 1` |
| 8T35 | 2 | 4461875 | `6746e8cd7253` | `6746e8cd7253` | `1, -3, 7, -12, 13, -12, 7, -3, 1` |
| 8T35 | 4 | 21550625 | `6746e8cd7253` | `6746e8cd7253` | `1, -3, 1, 6, -7, 2, 4, -4, 1` |
| 8T35 | 6 | 134560000 | `6746e8cd7253` | `6746e8cd7253` | `-1, 0, -3, 0, 10, 0, -6, 0, 1` |
| 8T35 | 8 | 1480160000 | `6746e8cd7253` | `6746e8cd7253` | `-1, 0, 24, 16, -38, -2, 19, -8, 1` |
| 8T38 | 0 | 374863125 | `6746e8cd7253` | `6746e8cd7253` | `9, 30, 91, 189, 225, 153, 59, 12, 1` |
| 8T38 | 2 | 62804734776 | `6746e8cd7253` | `6746e8cd7253` | `1, -4, 3, -5, 2, -5, 3, -4, 1` |
| 8T39 | 0 | 13424896 | `6746e8cd7253` | `6746e8cd7253` | `1, 0, 1, 0, 0, 0, 0, 0, 1` |
| 8T39 | 4 | 20502784 | `6746e8cd7253` | `6746e8cd7253` | `1, 0, -1, 0, 4, 0, -4, 0, 1` |
| 8T39 | 8 | 323296862464 | `6746e8cd7253` | `6746e8cd7253` | `1, 0, -10, 0, 19, 0, -9, 0, 1` |
| 8T40 | 0 | 89579520000 | `6746e8cd7253` | `6746e8cd7253` | `3, 0, 0, 0, 3, 0, -2, 0, 1` |
| 8T40 | 2 | 49836032 | `6746e8cd7253` | `6746e8cd7253` | `1, -2, 2, -4, 5, -4, 2, -2, 1` |
| 8T41 | 0 | 3398389014784 | `6746e8cd7253` | `6746e8cd7253` | `5, 14, 11, 4, 8, 4, 2, 0, 1` |
| 8T41 | 4 | 103539794176 | `6746e8cd7253` | `6746e8cd7253` | `3, -10, 9, -4, -4, 4, -2, 0, 1` |
| 8T42 | 0 | 38340864 | `6746e8cd7253` | `6746e8cd7253` | `4, -4, 8, -8, 6, -4, 4, 0, 1` |
| 8T44 | 0 | 1361513 | `6746e8cd7253` | `6746e8cd7253` | `1, 1, 2, 3, 3, 3, 2, 1, 1` |
| 8T44 | 2 | 4711123 | `6746e8cd7253` | `6746e8cd7253` | `1, 3, 5, 8, 9, 8, 5, 3, 1` |
| 8T44 | 4 | 24212981 | `6746e8cd7253` | `6746e8cd7253` | `1, -1, 2, 1, -7, 5, 3, -4, 1` |
| 8T44 | 6 | 493550656 | `6746e8cd7253` | `6746e8cd7253` | `-1, 0, 7, 0, 1, 0, -4, 0, 1` |
| 8T44 | 8 | 2941324032 | `6746e8cd7253` | `6746e8cd7253` | `-1, 12, 50, 0, -54, 10, 17, -8, 1` |
| 8T45 | 0 | 55115776 | `6746e8cd7253` | `6746e8cd7253` | `1, 0, 4, -4, 1, -4, 2, 0, 1` |
| 8T45 | 4 | 642318336 | `6746e8cd7253` | `6746e8cd7253` | `-2, -4, 0, 8, 6, -4, -4, 0, 1` |
| 8T46 | 4 | 964048826432 | `6746e8cd7253` | `6746e8cd7253` | `8, 14, 18, 8, -3, -4, -4, 0, 1` |
| 8T47 | 0 | 8577009 | `6746e8cd7253` | `6746e8cd7253` | `1, -1, 0, 2, 0, 2, 2, 0, 1` |
| 8T47 | 2 | 17269375 | `6746e8cd7253` | `6746e8cd7253` | `-1, 1, 0, -2, 2, 2, -2, 0, 1` |
| 8T47 | 4 | 43755625 | `6746e8cd7253` | `6746e8cd7253` | `-1, -1, -1, 4, 5, -2, -4, 0, 1` |
| 8T47 | 6 | 796999375 | `6746e8cd7253` | `6746e8cd7253` | `-1, -1, 4, -6, 8, 2, -6, 0, 1` |
| 8T50 | 0 | 6867832 | `3e5ae5aac772` | `6746e8cd7253` | `1, -1, 0, 1, 0, 0, 0, 0, 1` |
| 8T50 | 2 | 14733559 | `3e5ae5aac772` | `6746e8cd7253` | `-1, 0, 2, 0, 0, 3, 0, 0, 1` |
| 8T50 | 4 | 97258409 | `3e5ae5aac772` | `6746e8cd7253` | `-1, 0, 0, 0, 0, -4, 0, 3, 1` |
| 8T50 | 6 | 797603063 | `3e5ae5aac772` | `6746e8cd7253` | `1, 1, -16, 0, 20, 0, -8, 0, 1` |
| 8T50 | 8 | 9133507832384 | `6746e8cd7253` | `6746e8cd7253` | `32, 12, -128, 0, 80, 0, -16, 0, 1` |
