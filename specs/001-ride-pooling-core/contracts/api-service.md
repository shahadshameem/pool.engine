# Contract: Provider-Independent API Service Interface

**Interface**: `PoolEngineService` & ASGI 3 Application
**Namespace**: `engine.service`
**Purpose**: Expose a versioned, provider-neutral HTTP/ASGI service contract for external mobility systems to submit ride requests, register fleets, trigger real-time dispatch matching, and inspect pooled ride itineraries.

---

## 1. Architectural Boundaries & Non-Negotiable Invariants

1. **Framework Independence**:
   - The API layer is implemented as a pure standard-library ASGI 3 application callable (`create_app(service)`).
   - Zero required runtime dependencies on external web frameworks (no FastAPI or Starlette required).
   - Native integration with any standard ASGI server (e.g. Uvicorn, Hypercorn) or embeddable in FastAPI/Starlette routing trees.
2. **Separation of Concerns**:
   - The service layer delegates strictly to `DispatchOrchestrator` and `RideStorageProvider`.
   - Matching algorithms, seat capacity tracking, OCC version increments, and physical route validation are never duplicated in the API layer.
3. **Provider-Agnostic Schema**:
   - DTOs operate purely on canonical WGS84 geographic coordinates, Unix epoch timestamps (seconds), and canonical domain enums.
   - No vendor SDK assumptions (no OSRM, Valhalla, PostgreSQL, or cloud-specific schemas).

---

## 2. API Endpoints (`/v1`)

### A. Ride Requests

#### `POST /v1/requests`
Submits a new passenger demand request.

* **Request Body**:
```json
{
  "request_id": "req-101",
  "user_id": "usr-001",
  "pickup_location": {"latitude": 40.7580, "longitude": -73.9855},
  "dropoff_location": {"latitude": 40.7829, "longitude": -73.9654},
  "seat_count": 1,
  "earliest_pickup_time": 1700000000,
  "latest_dropoff_time": 1700001800,
  "direct_distance_meters": 3200,
  "direct_duration_seconds": 600
}
```
* **Routing Policy**:
  - If `direct_distance_meters` and `direct_duration_seconds` are provided, they are validated against positive physical bounds.
  - If omitted (`null`), they are calculated dynamically via the configured `RoadNetworkRoutingProvider`.
  - **Zero Haversine Fallback**: If routing computation fails or times out, the submission is rejected with `502 ROUTING_BACKEND_ERROR` or `504 ROUTING_TIMEOUT_ERROR`.
* **Status**: `201 Created`
* **Response**: Serialized canonical `RideRequest` in `PENDING` status.

#### `GET /v1/requests/{request_id}`
Retrieves the current state of a ride request.

* **Status**: `200 OK` or `404 Not Found`
* **Response**: Serialized `RideRequest` (`status`, `matched_ride_id`, timestamps, coordinates).

#### `POST /v1/requests/{request_id}/cancel`
Safely cancels a ride request while enforcing lifecycle invariants.

* **Request Body**: Optional `{"reason": "passenger_cancelled"}`
* **Behavior**:
  - `PENDING`: Transitions directly to `CANCELLED` in persistent storage.
  - `MATCHED`: Invokes `cancel_en_route_request()` to remove stops from the active ride itinerary, recalculate downstream ETAs, and increment the ride's OCC version.
  - `CANCELLED`: Idempotent `200 OK`.
  - `COMPLETED`, `EXPIRED`, or `IN_TRANSIT`: Rejects with `422 LIFECYCLE_ERROR`.
* **Status**: `200 OK` or `422 Unprocessable Entity`

---

### B. Vehicles & Fleet Management

#### `POST /v1/vehicles`
Registers an available vehicle in the fleet.

* **Request Body**:
```json
{
  "vehicle_id": "veh-101",
  "driver_id": "drv-201",
  "total_seat_capacity": 4,
  "current_location": {"latitude": 40.7500, "longitude": -73.9900},
  "is_active": true,
  "luggage_capacity_units": 2
}
```
* **Status**: `201 Created`
* **Idempotency**: Submitting identical configuration returns the existing vehicle (`201 Created`). Conflicting attributes return `409 CONCURRENCY_CONFLICT`.

#### `GET /v1/vehicles/{vehicle_id}`
Retrieves vehicle availability and telemetry location.

* **Status**: `200 OK` or `404 Not Found`

#### `PATCH /v1/vehicles/{vehicle_id}/location`
Updates a vehicle's current telemetry coordinates.

* **Request Body**:
```json
{
  "latitude": 40.7545,
  "longitude": -73.9870
}
```
* **Status**: `200 OK` or `404 Not Found`

#### `PATCH /v1/vehicles/{vehicle_id}/status`
Updates operational availability (`is_active: bool`).

* **Status**: `200 OK` or `404 Not Found`

---

### C. Dispatch Orchestration

#### `POST /v1/dispatch`
Triggers an end-to-end bounded optimization and atomic commit cycle.

* **Headers**: Optional `Idempotency-Key: <token>`
* **Request Body**:
```json
{
  "current_time": 1700000300,
  "cycle_id": "cycle-001",
  "idempotency_token": "token-001",
  "deadline_seconds": 0.500,
  "request_limit": 500,
  "vehicle_limit": 100
}
```
* **Idempotency Rules**:
  - If both `Idempotency-Key` header and body `idempotency_token` are provided and differ, the request is rejected with `400 VALIDATION_ERROR`.
  - Replaying a request with an existing idempotency token returns the cached `DispatchCycleResponse` with zero side effects or duplicate solver execution.
* **Status**: `200 OK`
* **Response**: `DispatchCycleResponse` containing:
  - `cycle_id`, `batch_id`, `timestamp`
  - `search_status` (`COMPLETE`, `APPROXIMATED`, `INCOMPLETE_DEADLINE_EXPIRED`, `INCOMPLETE_ROUTING_ERROR`)
  - `is_approximated` (bool)
  - `total_vmt_savings_meters` (int)
  - `cycle_duration_ms` (float)
  - `routing_errors_count` (int)
  - `committed_assignments`: List of assignments committed atomically to storage.
  - `rejected_assignments`: Diagnostics for assignments rejected due to OCC or capacity conflicts.
  - `unassigned_request_ids`: Requests left pending for subsequent dispatch windows.

---

### D. Pooled Rides & Route State

#### `GET /v1/rides/{ride_id}`
Retrieves the complete pooled ride itinerary, ordered stops, passenger count, and OCC version.

* **Status**: `200 OK` or `404 Not Found`
* **Response**: Serialized canonical `Ride` model.

#### `GET /v1/health`
Health and readiness probe.

* **Status**: `200 OK`
* **Response**: `{"status": "ok", "service": "pool-engine"}`

---

## 3. Structured Error Contract (RFC 7807)

All non-2xx responses return a uniform error envelope:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Request input validation failed",
    "details": [
      {
        "field": "seat_count",
        "issue": "Input should be greater than or equal to 1"
      }
    ]
  }
}
```

| HTTP Status Code | Error Code | Trigger Condition |
| :--- | :--- | :--- |
| **400 Bad Request** | `VALIDATION_ERROR` | Schema failure, out-of-bounds coordinates, inverted time window, mismatched idempotency tokens. |
| **404 Not Found** | `RESOURCE_NOT_FOUND` | Missing request, vehicle, ride, or route path. |
| **405 Method Not Allowed** | `METHOD_NOT_ALLOWED` | HTTP verb not supported for the requested resource path. |
| **409 Conflict** | `CONCURRENCY_CONFLICT` | OCC version mismatch, capacity exhaustion, or registration conflict. |
| **422 Unprocessable Entity** | `LIFECYCLE_ERROR` | Illegal state transition (e.g. cancelling onboarded passenger or completed ride). |
| **502 Bad Gateway** | `ROUTING_BACKEND_ERROR` | Road routing provider lookup failure or invalid leg geometry. |
| **504 Gateway Timeout** | `ROUTING_TIMEOUT_ERROR` | Upstream routing backend exceeded query deadline. |
| **500 Internal Error** | `INTERNAL_SERVER_ERROR` | Unhandled runtime exception. |

---

## 4. Storage Guarantees & Documented Limitations

### Atomic Operations
- **Dispatch Commits**: `RideStorageProvider.commit_dispatch_assignment_atomic()` provides strict transactional guarantees:
  - Active vehicle lock (`SELECT ... FOR UPDATE` in PostgreSQL).
  - Optimistic concurrency control (OCC) validating expected ride version.
  - Atomic transition of all matched requests from `PENDING` to `MATCHED`.
  - Atomic insertion of new or updated `Ride` and `RouteStop` rows.
  - Safe replay on identical idempotency tokens.
- **Assigned Request Cancellation**: `RideStorageProvider.cancel_assigned_request_atomic()` guarantees single-transaction atomicity:
  - Row-level lock on `rides` (`SELECT ... FOR UPDATE`) enforcing OCC version check.
  - Row-level lock on `ride_requests` (`SELECT ... FOR UPDATE`).
  - Row-level lock on `route_stops` checking passenger boarding state (rejecting if pickup completed).
  - Atomic stop itinerary replacement, ride version increment, and request status transition to `CANCELLED`.
  - Complete Rollback: Any constraint or transaction failure rolls back both ride and request updates together.

### Distributed Transaction Scope
- Atomicity is guaranteed at the storage engine level (PostgreSQL transaction / ACID boundary or in-memory lock).
- This does not claim distributed two-phase commit across external payment or fleet networks.

---

## 5. Performance SLA Disclaimer

The sub-500 ms SLA benchmark qualification ($\le 500\text{ms}$ dispatch cycle) applies strictly to the tested 1,000-request / 200-vehicle Manhattan regional road graph with a fully warm negative/positive routing cache. It does not represent cold-cache queries or arbitrary unconstrained global bounding boxes.
