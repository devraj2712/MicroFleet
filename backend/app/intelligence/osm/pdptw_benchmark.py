import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union
from pydantic import BaseModel, Field


class PDPTWNode(BaseModel):
    """A customer or depot node in the Li & Lim PDPTW benchmark."""
    cust_no: int
    x: float
    y: float
    demand: float
    ready_time: float
    due_date: float
    service_time: float
    pickup_node: int
    delivery_node: int

    @property
    def is_depot(self) -> bool:
        return self.cust_no == 0

    @property
    def is_pickup(self) -> bool:
        return self.cust_no != 0 and self.pickup_node == 0 and self.delivery_node > 0

    @property
    def is_delivery(self) -> bool:
        return self.cust_no != 0 and self.delivery_node == 0 and self.pickup_node > 0


class PDPTWRequestPair(BaseModel):
    """Normalized paired pickup and delivery logistics request."""
    request_id: int
    pickup_cust_no: int
    delivery_cust_no: int
    demand: float
    pickup_ready_time: float
    pickup_due_date: float
    delivery_ready_time: float
    delivery_due_date: float
    pickup_service_time: float
    delivery_service_time: float


class PDPTWInstance(BaseModel):
    """Normalized representation of a complete Li & Lim PDPTW benchmark instance."""
    instance_name: str
    source_attribution: str = "SINTEF Applied Mathematics / Li & Lim (2001) Benchmark"
    license_note: str = "Freely accessible for scientific, educational and academic research benchmarking."
    coordinate_domain: str = (
        "ABSTRACT_EUCLIDEAN_2D: Coordinates represent abstract plane benchmark points, "
        "not geographic latitude/longitude. Distance and travel times are computed as standard Euclidean metrics."
    )
    vehicle_number: int
    vehicle_capacity: float
    depot: PDPTWNode
    nodes: Dict[int, PDPTWNode]
    requests: List[PDPTWRequestPair]
    node_indices: List[int]
    euclidean_distance_matrix: List[List[float]]
    validation_status: str
    validation_notes: List[str] = Field(default_factory=list)


def parse_pdptw_text(raw_text: str, instance_name: str = "PDPTW_INSTANCE") -> PDPTWInstance:
    """Parse raw Li & Lim tab/whitespace-delimited text into a normalized PDPTWInstance.

    Format specification (SINTEF TOP PDPTW):
      Line 1: NUMBER_OF_VEHICLES  CAPACITY
      Line 2: [Header or Empty]
      Line 3+: CUST_NO  XCOORD  YCOORD  DEMAND  READY_TIME  DUE_DATE  SERVICE_TIME  PICKUP  DELIVERY
    """
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    if not lines:
        raise ValueError("Cannot parse empty benchmark content.")

    # Parse first line (vehicles and capacity)
    first_tokens = lines[0].split()
    if len(first_tokens) < 2:
        raise ValueError(f"Invalid benchmark header line '{lines[0]}'. Expected: <VEHICLE_NUM> <CAPACITY>.")
    
    vehicle_number = int(first_tokens[0])
    vehicle_capacity = float(first_tokens[1])

    # Parse node rows
    nodes: Dict[int, PDPTWNode] = {}
    validation_notes: List[str] = []

    for line in lines[1:]:
        # Skip column header row if present
        if "CUST" in line.upper() or "XCOORD" in line.upper():
            continue

        tokens = line.split()
        if len(tokens) < 9:
            continue

        cust_no = int(tokens[0])
        x = float(tokens[1])
        y = float(tokens[2])
        demand = float(tokens[3])
        ready_time = float(tokens[4])
        due_date = float(tokens[5])
        service_time = float(tokens[6])
        pickup_node = int(tokens[7])
        delivery_node = int(tokens[8])

        node = PDPTWNode(
            cust_no=cust_no,
            x=x,
            y=y,
            demand=demand,
            ready_time=ready_time,
            due_date=due_date,
            service_time=service_time,
            pickup_node=pickup_node,
            delivery_node=delivery_node,
        )
        nodes[cust_no] = node

    if 0 not in nodes:
        raise ValueError("Benchmark instance must contain depot node with CUST NO. = 0.")

    depot = nodes[0]
    if depot.demand != 0:
        validation_notes.append(f"Depot node 0 has non-zero demand ({depot.demand}). Expected 0.")

    # Validate pairing and assemble requests
    requests: List[PDPTWRequestPair] = []
    req_counter = 1

    for cust_id, node in nodes.items():
        if cust_id == 0:
            continue

        # Check time window validity
        if node.ready_time > node.due_date:
            validation_notes.append(
                f"Node {cust_id} time window inverted: ready_time ({node.ready_time}) > due_date ({node.due_date})."
            )

        # Process pickup nodes
        if node.is_pickup:
            deliv_id = node.delivery_node
            if deliv_id not in nodes:
                validation_notes.append(
                    f"Pickup node {cust_id} specifies delivery node {deliv_id} which does not exist in instance."
                )
                continue

            deliv_node = nodes[deliv_id]
            # Verify cross-reference
            if deliv_node.pickup_node != cust_id:
                validation_notes.append(
                    f"Pairing mismatch: Pickup {cust_id} points to delivery {deliv_id}, "
                    f"but delivery {deliv_id} points to pickup {deliv_node.pickup_node}."
                )

            # Verify demand symmetry
            if node.demand != -deliv_node.demand:
                validation_notes.append(
                    f"Demand symmetry mismatch: Pickup {cust_id} demand is {node.demand}, "
                    f"delivery {deliv_id} demand is {deliv_node.demand} (expected {-node.demand})."
                )

            # Verify vehicle capacity constraint
            if node.demand > vehicle_capacity:
                validation_notes.append(
                    f"Demand {node.demand} for request at node {cust_id} exceeds vehicle capacity {vehicle_capacity}."
                )

            requests.append(
                PDPTWRequestPair(
                    request_id=req_counter,
                    pickup_cust_no=cust_id,
                    delivery_cust_no=deliv_id,
                    demand=node.demand,
                    pickup_ready_time=node.ready_time,
                    pickup_due_date=node.due_date,
                    delivery_ready_time=deliv_node.ready_time,
                    delivery_due_date=deliv_node.due_date,
                    pickup_service_time=node.service_time,
                    delivery_service_time=deliv_node.service_time,
                )
            )
            req_counter += 1

    # Compute Euclidean distance matrix for abstract coordinates
    sorted_node_ids = sorted(nodes.keys())
    matrix_dim = len(sorted_node_ids)
    dist_matrix: List[List[float]] = [[0.0] * matrix_dim for _ in range(matrix_dim)]

    for i, id_i in enumerate(sorted_node_ids):
        n_i = nodes[id_i]
        for j, id_j in enumerate(sorted_node_ids):
            if i == j:
                dist_matrix[i][j] = 0.0
            else:
                n_j = nodes[id_j]
                dx = n_i.x - n_j.x
                dy = n_i.y - n_j.y
                dist_matrix[i][j] = round(math.hypot(dx, dy), 4)

    validation_status = "VALID" if len(validation_notes) == 0 else "WARNINGS_FOUND"

    return PDPTWInstance(
        instance_name=instance_name,
        vehicle_number=vehicle_number,
        vehicle_capacity=vehicle_capacity,
        depot=depot,
        nodes=nodes,
        requests=requests,
        node_indices=sorted_node_ids,
        euclidean_distance_matrix=dist_matrix,
        validation_status=validation_status,
        validation_notes=validation_notes,
    )


def parse_pdptw_file(filepath: Union[str, Path]) -> PDPTWInstance:
    """Read and parse a Li & Lim PDPTW instance file."""
    path = Path(filepath).resolve()
    if not path.exists():
        raise FileNotFoundError(f"PDPTW benchmark file not found at: {path}")

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    return parse_pdptw_text(content, instance_name=path.stem)
