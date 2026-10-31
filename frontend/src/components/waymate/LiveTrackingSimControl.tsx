import { useState } from "react"
import { MaterialIcon } from "../common/MaterialIcon"
import { liveLocationService } from "../../services/location/liveLocationService"
import type { LiveUserLocation } from "../../services/location/liveLocationService"

interface LiveTrackingSimControlProps {
  rideId: string
  currentUserId?: string
  currentUserName?: string
  role?: string
  myLocation: LiveUserLocation | null
  peerLocation?: LiveUserLocation | null
  destinationCoords?: { lat: number; lng: number }
  onSimulateLocation: (lat: number, lng: number, heading?: number) => void
  onSimulateCoRiderLocation?: (id: string, name: string, lat: number, lng: number) => void
}

export function LiveTrackingSimControl({
  rideId,
  currentUserId: _currentUserId = "mock-user",
  currentUserName = "You",
  role = "participant",
  myLocation: _myLocation,
  peerLocation: _peerLocation,
  destinationCoords = { lat: 8.4891, lng: 76.9498 },
  onSimulateLocation,
  onSimulateCoRiderLocation
}: LiveTrackingSimControlProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [stepIndex, setStepIndex] = useState(0)

  // Only render in dev environment or when testing
  const isDev = import.meta.env.DEV || (typeof window !== "undefined" && window.location.search.includes("dev=true"))
  if (!isDev) return null

  const baseLat = 8.5459
  const baseLng = 76.9063

  // 1. Move "You" closer to campus pickup point (<= 30m "You've met")
  const approachSteps = [
    { label: "150m", offsetLat: 0.0012, offsetLng: 0.0010, heading: 45 },
    { label: "60m", offsetLat: 0.0005, offsetLng: 0.0004, heading: 45 },
    { label: "25m (Met!)", offsetLat: 0.00018, offsetLng: 0.00015, heading: 45 },
    { label: "8m (Met!)", offsetLat: 0.00005, offsetLng: 0.00005, heading: 45 }
  ]

  const handleStepCloser = () => {
    const nextIdx = (stepIndex + 1) % approachSteps.length
    setStepIndex(nextIdx)
    const step = approachSteps[nextIdx]
    const newLat = baseLat + step.offsetLat
    const newLng = baseLng + step.offsetLng
    onSimulateLocation(newLat, newLng, step.heading)
  }

  const handleMoveFarther = () => {
    const newLat = baseLat + 0.0065
    const newLng = baseLng + 0.0055
    onSimulateLocation(newLat, newLng, 180)
  }

  // 2. Spawn / Move Fake Co-Rider 1 ("Anu")
  const handleSimulateAnu = async (proximity: "far" | "near" | "met") => {
    const offset = proximity === "far" ? 0.0035 : proximity === "near" ? 0.0007 : 0.00015
    const lat = baseLat + offset
    const lng = baseLng + offset

    if (onSimulateCoRiderLocation) {
      onSimulateCoRiderLocation("sim-corider-anu", "Anu", lat, lng)
    }

    // Also persist to Firestore so all connected devices/sessions see Anu in real time
    const loc: LiveUserLocation = {
      rideId,
      userId: "sim-corider-anu",
      userName: "Anu",
      isCreator: false,
      role: "co-rider",
      lat,
      lng,
      heading: 90,
      speed: 1.2,
      accuracy: 6,
      isSharing: true
    }
    await liveLocationService.updateLiveLocation(rideId, loc)
  }

  // 3. Spawn / Move Fake Co-Rider 2 ("Rahul")
  const handleSimulateRahul = async (proximity: "far" | "near" | "met") => {
    const offset = proximity === "far" ? 0.0040 : proximity === "near" ? 0.0009 : 0.00012
    const lat = baseLat - offset
    const lng = baseLng + offset

    if (onSimulateCoRiderLocation) {
      onSimulateCoRiderLocation("sim-corider-rahul", "Rahul", lat, lng)
    }

    const loc: LiveUserLocation = {
      rideId,
      userId: "sim-corider-rahul",
      userName: "Rahul",
      isCreator: false,
      role: "co-rider",
      lat,
      lng,
      heading: 270,
      speed: 1.1,
      accuracy: 7,
      isSharing: true
    }
    await liveLocationService.updateLiveLocation(rideId, loc)
  }

  // 4. Drive cab towards destination (Phase B testing)
  const handleDriveStep = (fraction: number) => {
    const startLat = baseLat
    const startLng = baseLng
    const targetLat = destinationCoords.lat
    const targetLng = destinationCoords.lng

    const simLat = startLat + (targetLat - startLat) * fraction
    const simLng = startLng + (targetLng - startLng) * fraction
    onSimulateLocation(simLat, simLng, 135)
  }

  // 5. Test Route Engine: Step-by-step trimming and off-route deviation
  const [trimStep, setTrimStep] = useState(0)
  const handleWalkAlongRoute = () => {
    const trimSteps = [
      { offsetLat: 0.0020, offsetLng: 0.0018, heading: 225 },
      { offsetLat: 0.0012, offsetLng: 0.0010, heading: 225 },
      { offsetLat: 0.0006, offsetLng: 0.0005, heading: 225 },
      { offsetLat: 0.0001, offsetLng: 0.0001, heading: 225 }
    ]
    const step = trimSteps[trimStep]
    setTrimStep((trimStep + 1) % trimSteps.length)
    onSimulateLocation(baseLat + step.offsetLat, baseLng + step.offsetLng, step.heading)
  }

  const handleDeviateOffRoute = () => {
    // Shift 90 meters perpendicular away from route corridor to trigger >30m off-route detection
    onSimulateLocation(baseLat + 0.0015, baseLng + 0.0028, 90)
  }

  return (
    <div className="fixed bottom-[140px] left-3 z-[9999] font-sans">
      {!isOpen ? (
        <button
          type="button"
          onClick={() => setIsOpen(true)}
          className="bg-black/90 text-[#C5FF00] border border-[#C5FF00]/60 shadow-xl rounded-full px-3 py-1.5 text-xs font-bold flex items-center gap-1.5 backdrop-blur-md hover:bg-black active:scale-95 transition-all cursor-pointer"
        >
          <MaterialIcon name="science" className="text-sm text-[#C5FF00]" />
          <span>Pool Sim</span>
        </button>
      ) : (
        <div className="bg-[#121212]/95 backdrop-blur-md border border-zinc-700 rounded-2xl p-3.5 shadow-2xl text-white w-72 space-y-2.5 animate-in fade-in zoom-in-95 duration-150">
          <div className="flex items-center justify-between pb-1 border-b border-zinc-800">
            <div className="flex items-center gap-1.5 text-xs font-black text-[#C5FF00]">
              <MaterialIcon name="science" className="text-base" />
              <span>Campus Pool Simulator</span>
            </div>
            <button
              type="button"
              onClick={() => setIsOpen(false)}
              className="text-zinc-400 hover:text-white text-xs font-bold p-1 cursor-pointer"
            >
              ✕
            </button>
          </div>

          <div className="text-[11px] text-zinc-400">
            Participant: <span className="text-white font-bold">{currentUserName}</span> ({role})
          </div>

          {/* 1. Simulate "You" moving to pickup */}
          <div className="space-y-1.5">
            <div className="text-[10px] text-zinc-400 uppercase font-bold tracking-wider">Move You to Pickup</div>
            <div className="grid grid-cols-2 gap-1.5">
              <button
                type="button"
                onClick={handleStepCloser}
                className="bg-zinc-800 hover:bg-zinc-700 text-xs font-bold py-1.5 px-2 rounded-lg text-emerald-400 border border-emerald-500/30 flex items-center justify-center gap-1 cursor-pointer"
              >
                <span>Approach ({approachSteps[stepIndex].label})</span>
              </button>
              <button
                type="button"
                onClick={handleMoveFarther}
                className="bg-zinc-800 hover:bg-zinc-700 text-xs font-bold py-1.5 px-2 rounded-lg text-zinc-300 border border-zinc-700 flex items-center justify-center gap-1 cursor-pointer"
              >
                <span>Move Away</span>
              </button>
            </div>
          </div>

          {/* 2. Co-Rider Simulations */}
          <div className="space-y-1.5">
            <div className="text-[10px] text-zinc-400 uppercase font-bold tracking-wider">Simulate Co-Riders</div>
            <div className="grid grid-cols-2 gap-1.5">
              <button
                type="button"
                onClick={() => handleSimulateAnu("near")}
                className="bg-zinc-800 hover:bg-zinc-700 text-[11px] font-bold py-1 px-1.5 rounded-lg text-teal-300 border border-teal-500/30 text-center cursor-pointer"
              >
                Anu (400m)
              </button>
              <button
                type="button"
                onClick={() => handleSimulateAnu("met")}
                className="bg-zinc-800 hover:bg-zinc-700 text-[11px] font-bold py-1 px-1.5 rounded-lg text-[#C5FF00] border border-[#C5FF00]/40 text-center cursor-pointer"
              >
                Anu (Met!)
              </button>
            </div>
            <div className="grid grid-cols-2 gap-1.5">
              <button
                type="button"
                onClick={() => handleSimulateRahul("near")}
                className="bg-zinc-800 hover:bg-zinc-700 text-[11px] font-bold py-1 px-1.5 rounded-lg text-teal-300 border border-teal-500/30 text-center cursor-pointer"
              >
                Rahul (600m)
              </button>
              <button
                type="button"
                onClick={() => handleSimulateRahul("met")}
                className="bg-zinc-800 hover:bg-zinc-700 text-[11px] font-bold py-1 px-1.5 rounded-lg text-[#C5FF00] border border-[#C5FF00]/40 text-center cursor-pointer"
              >
                Rahul (Met!)
              </button>
            </div>
          </div>

          {/* 3. Phase B: Cab En Route */}
          <div className="space-y-1.5">
            <div className="text-[10px] text-zinc-400 uppercase font-bold tracking-wider">Cab to Destination (Phase B)</div>
            <div className="grid grid-cols-3 gap-1">
              <button
                type="button"
                onClick={() => handleDriveStep(0.25)}
                className="bg-zinc-800 hover:bg-zinc-700 text-[11px] font-bold py-1 px-1 rounded text-blue-400 border border-blue-500/30 text-center cursor-pointer"
              >
                25%
              </button>
              <button
                type="button"
                onClick={() => handleDriveStep(0.50)}
                className="bg-zinc-800 hover:bg-zinc-700 text-[11px] font-bold py-1 px-1 rounded text-blue-400 border border-blue-500/30 text-center cursor-pointer"
              >
                50%
              </button>
              <button
                type="button"
                onClick={() => handleDriveStep(0.90)}
                className="bg-zinc-800 hover:bg-zinc-700 text-[11px] font-bold py-1 px-1 rounded text-blue-400 border border-blue-500/30 text-center cursor-pointer"
              >
                90%
              </button>
            </div>
          </div>

          {/* 4. Routing Engine: Trimming & Deviation Tests */}
          <div className="space-y-1.5 pt-1 border-t border-zinc-800">
            <div className="text-[10px] text-zinc-400 uppercase font-bold tracking-wider">Route Engine Tests</div>
            <div className="grid grid-cols-2 gap-1.5">
              <button
                type="button"
                onClick={handleWalkAlongRoute}
                className="bg-zinc-800 hover:bg-zinc-700 text-[11px] font-bold py-1.5 px-2 rounded-lg text-[#C5FF00] border border-[#C5FF00]/30 flex items-center justify-center gap-1 cursor-pointer"
                title="Walk along route to test dynamic line trimming without API calls"
              >
                <span>🚶 Step Trim ({trimStep + 1}/4)</span>
              </button>
              <button
                type="button"
                onClick={handleDeviateOffRoute}
                className="bg-zinc-800 hover:bg-zinc-700 text-[11px] font-bold py-1.5 px-2 rounded-lg text-amber-300 border border-amber-500/30 flex items-center justify-center gap-1 cursor-pointer"
                title="Step 90m off route to trigger deviation threshold and reroute"
              >
                <span>⚠️ Go Off-Route</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
