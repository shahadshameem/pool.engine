# Contract: SpatialIndexProvider

**Interface**: `SpatialIndexProvider`  
**Namespace**: `engine.contracts.spatial`  
**Purpose**: Decouple the matching engine from specific spatial indexing libraries (Uber H3, Google S2, Geohash, R-Tree), providing provider-neutral candidate neighborhood discovery.

---

## 1. Interface Definition (Python Abstract Base Class)

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Sequence, Optional
from engine.contracts.routing import Coordinate

@dataclass(frozen=True)
class SpatialCandidate:
    entity_id: str
    location: Coordinate
    haversine_distance_meters: float
    cell_id: str

class SpatialIndexProvider(ABC):
    """
    Vendor-independent spatial indexing contract.
    Provides fast discrete O(1) or O(log N) neighbor candidate discovery.
    """

    @abstractmethod
    def index_entities(
        self,
        entities: Sequence[tuple[str, Coordinate]]
    ) -> None:
        """
        Indexes a batch of spatial entities (e.g., active vehicles or pickup stops).
        """
        pass

    @abstractmethod
    def find_nearest_candidates(
        self,
        target: Coordinate,
        max_radius_meters: float,
        min_candidates: int = 5,
        max_candidates: int = 50
    ) -> Sequence[SpatialCandidate]:
        """
        Queries nearest candidate entities within max_radius_meters.
        If fewer than min_candidates are found in the initial cell/ring,
        the implementation adaptively expands search rings up to max_radius_meters.
        """
        pass

    @abstractmethod
    def get_cell_id(self, coordinate: Coordinate) -> str:
        """
        Returns the canonical string representation of the spatial cell
        containing the given coordinate at default resolution.
        """
        pass
```

## 2. Invariants, Mathematical Pruning Proofs & Fallback Semantics

### 2.1 Mathematical Proof of Safe Pruning (Zero Feasible Candidate Elimination)
- **Theorem (Safe Metric Lower Bound)**: Let $x_v$ be a vehicle location at current time $t$ and $x_p$ be a pickup coordinate with earliest pickup time $t_r$ and maximum allowable pickup delay $\Delta T_{\text{delay}} = \text{max\_pickup\_delay\_seconds}$. Let $v_{\max}$ be the maximum physical road speed limit attainable anywhere on the service network.
  1. *Road vs. Haversine Metric Bound*: On the Earth's surface, the great-circle Haversine distance $d_{\text{haversine}}(x_v, x_p)$ is the geodesic, strictly bounding road network distance from below:
     $$d_{\text{road}}(x_v, x_p) \ge d_{\text{haversine}}(x_v, x_p)$$
  2. *Travel Time Lower Bound*: Since actual vehicle speed $v_{\text{road}}(t) \le v_{\max}$ for all road segments:
     $$\text{TravelTime}_{\text{road}}(x_v, x_p) = \int \frac{1}{v_{\text{road}}(s)} ds \ge \frac{d_{\text{road}}(x_v, x_p)}{v_{\max}} \ge \frac{d_{\text{haversine}}(x_v, x_p)}{v_{\max}}$$
  3. *Pruning Condition*: If $\frac{d_{\text{haversine}}(x_v, x_p)}{v_{\max}} > \max\left(0, t_r + \Delta T_{\text{delay}} - t\right)$, then $\text{TravelTime}_{\text{road}}(x_v, x_p) > \Delta T_{\text{available}}$ strictly holds on every conceivable road network.
  4. *Conclusion*: Pruning any candidate pairing where $d_{\text{haversine}}(x_v, x_p) > R_{\text{search\_max}} \equiv v_{\max} \cdot \Delta T_{\text{delay}}$ mathematically CANNOT eliminate any physically feasible candidate. $\blacksquare$

### 2.2 Adaptive Multi-Ring Neighborhood Expansion & Exact Termination
- **Expansion Protocol**: For a target coordinate $x_p$ in spatial cell $C_0$, discrete indexing searches concentric cell rings $k = 0, 1, 2, \dots$
- **Ring Coverage Metric**: Let $r_{\text{inner\_min}}(k)$ denote the minimum distance from the cell centroid/boundary to the outer boundary of the $k$-ring.
- **Exact Termination Conditions**: Ring expansion MUST terminate if and only if either:
  1. *Full Coverage Termination*: $r_{\text{inner\_min}}(k) \ge R_{\text{search\_max}} = v_{\max} \cdot \Delta T_{\text{delay}}$. All points within the physical reachability limit have been visited.
  2. *Capacity Bounded Termination*: The accumulated candidate count reaches `max_candidates` AND all contiguous cells in the current ring $k$ have been completely processed (preventing directional selection bias).

### 2.3 Mandatory Exhaustive Fallback & Derived Bounding-Box Proof
- **When Fallback is Required**: A concrete spatial provider MUST automatically invoke exhaustive fallback when:
  1. An indexing fault, unhandled boundary exception, or missing cell definition occurs.
  2. Target coordinate lies near a spherical discontinuity (antimeridian $\pm 180^\circ$ or polar latitude $|\phi| > 85^\circ$).
  3. The provider hits its maximum configured ring expansion limit ($k_{\text{limit}}$) before achieving $r_{\text{inner\_min}}(k) \ge R_{\text{search\_max}}$, AND candidate count $< \text{min\_candidates}$.
- **Derived Bounding-Box Sufficiency**:
  Let target coordinate be $(\phi_0, \lambda_0)$ in radians with mean Earth radius $R_{\text{earth}} \approx 6,371,000\text{ m}$.
  Define angular radius $\Delta \sigma = \frac{R_{\text{search\_max}}}{R_{\text{earth}}}$.
  Define maximum absolute latitude across the search band:
  $$\phi_{\text{max\_abs}} = \min\left(\frac{\pi}{2} - 10^{-6}, \max(|\phi_0 - \Delta \sigma|, |\phi_0 + \Delta \sigma|)\right)$$
  Define latitude half-width $\Delta \phi = \Delta \sigma$ and longitude half-width $\Delta \lambda = \frac{\Delta \sigma}{\cos(\phi_{\text{max\_abs}})}$.
  The derived bounding box is:
  $$\text{BBox}(x_0, R_{\text{search\_max}}) = [\phi_0 - \Delta \phi, \lambda_0 - \Delta \lambda, \phi_0 + \Delta \phi, \lambda_0 + \Delta \lambda]$$
  *Proof of Completeness*: For any coordinate $x = (\phi, \lambda)$ with $d_{\text{haversine}}(x_0, x) \le R_{\text{search\_max}}$, the spherical distance $\sigma(x_0, x) \le \Delta \sigma$. By Haversine decomposition:
  $$\sin^2\left(\frac{\Delta \sigma}{2}\right) \ge \sin^2\left(\frac{\phi - \phi_0}{2}\right) + \cos(\phi_0)\cos(\phi)\sin^2\left(\frac{\lambda - \lambda_0}{2}\right)$$
  Non-negativity of terms guarantees $|\phi - \phi_0| \le \Delta \sigma = \Delta \phi$ and $|\lambda - \lambda_0| \le \Delta \lambda$. Thus $x \in \text{BBox}$.
  Filtering entities within this derived $\text{BBox}$ followed by exact Haversine distance verification is mathematically proven to guarantee **100% complete recall** of all candidates within $R_{\text{search\_max}}$. $\blacksquare$

### 2.4 Fixture Recall Verification Contract
- **Test Fixture Verification**: On all defined benchmark test fixtures, concrete implementations MUST achieve **100% candidate recall** of all physically feasible pooled pairings identified by an exhaustive brute-force all-pairs search. Any dropped feasible candidate on test fixtures constitutes an immediate test failure.
