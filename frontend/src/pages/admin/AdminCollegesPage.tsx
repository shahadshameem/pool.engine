import { useState, useEffect } from "react"
import { MaterialIcon } from "../../components/common/MaterialIcon"
import { useToast } from "../../components/feedback/ToastContext"
import { collegeService, type College, DEFAULT_COLLEGES } from "../../services/college/collegeService"

export function AdminCollegesPage() {
  const { showToast } = useToast()

  const [colleges, setColleges] = useState<College[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState("")
  const [statusFilter, setStatusFilter] = useState<string>("all")

  // Modal State
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [editingCollege, setEditingCollege] = useState<College | null>(null)
  const [isSaving, setIsSaving] = useState(false)

  // Form State
  const [formData, setFormData] = useState({
    code: "",
    name: "",
    shortName: "",
    city: "",
    state: "Kerala",
    status: "active" as "active" | "onboarding" | "paused",
    allowedDomains: "",
    locationName: "",
    latitude: "8.5458",
    longitude: "76.9032",
    departments: "CSE, ECE, EEE, ME, CE, ARCH"
  })

  useEffect(() => {
    loadColleges()
  }, [])

  const loadColleges = async (force = false) => {
    setIsLoading(true)
    try {
      const data = await collegeService.getColleges(false, force)
      setColleges(data)
    } catch (e) {
      console.error("Error loading colleges:", e)
      showToast("Failed to load colleges from Firestore.", "error")
      setColleges(DEFAULT_COLLEGES)
    } finally {
      setIsLoading(false)
    }
  }

  const handleOpenAddModal = () => {
    setEditingCollege(null)
    setFormData({
      code: "",
      name: "",
      shortName: "",
      city: "",
      state: "Kerala",
      status: "active",
      allowedDomains: "",
      locationName: "",
      latitude: "8.5458",
      longitude: "76.9032",
      departments: "CSE, ECE, EEE, ME, CE, ARCH"
    })
    setIsModalOpen(true)
  }

  const handleOpenEditModal = (col: College) => {
    setEditingCollege(col)
    setFormData({
      code: col.code || "",
      name: col.name || "",
      shortName: col.shortName || "",
      city: col.city || "",
      state: col.state || "Kerala",
      status: col.status || "active",
      allowedDomains: (col.allowedDomains || []).join(", "),
      locationName: col.location?.name || "",
      latitude: String(col.location?.latitude ?? 8.5458),
      longitude: String(col.location?.longitude ?? 76.9032),
      departments: (col.departments || []).map(d => d.code).join(", ")
    })
    setIsModalOpen(true)
  }

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!formData.name.trim() || !formData.code.trim()) {
      showToast("College Name and Short Code are required.", "error")
      return
    }

    setIsSaving(true)
    try {
      const parsedDomains = formData.allowedDomains
        .split(",")
        .map(d => d.trim().toLowerCase())
        .filter(Boolean)

      const parsedDepts = formData.departments
        .split(",")
        .map(d => d.trim().toUpperCase())
        .filter(Boolean)
        .map(code => ({ code, name: code }))

      const lat = parseFloat(formData.latitude) || 8.5458
      const lng = parseFloat(formData.longitude) || 76.9032

      if (editingCollege) {
        await collegeService.updateCollege(editingCollege.id, {
          name: formData.name.trim(),
          shortName: formData.shortName.trim() || formData.code.trim(),
          code: formData.code.trim().toUpperCase(),
          city: formData.city.trim(),
          state: formData.state.trim(),
          status: formData.status,
          allowedDomains: parsedDomains,
          location: {
            name: formData.locationName.trim() || `${formData.name} Main Campus`,
            latitude: lat,
            longitude: lng
          },
          departments: parsedDepts
        })
        showToast("College updated successfully!", "success")
      } else {
        await collegeService.createCollege({
          name: formData.name.trim(),
          shortName: formData.shortName.trim() || formData.code.trim(),
          code: formData.code.trim().toUpperCase(),
          city: formData.city.trim(),
          state: formData.state.trim(),
          status: formData.status,
          allowedDomains: parsedDomains,
          location: {
            name: formData.locationName.trim() || `${formData.name} Main Campus`,
            latitude: lat,
            longitude: lng
          },
          departments: parsedDepts
        })
        showToast("College onboarded successfully!", "success")
      }

      setIsModalOpen(false)
      await loadColleges(true)
    } catch (err: any) {
      console.error("Failed to save college:", err)
      showToast(err?.message || "Failed to save college", "error")
    } finally {
      setIsSaving(false)
    }
  }

  const handleToggleStatus = async (col: College) => {
    const nextStatus = col.status === "active" ? "paused" : "active"
    try {
      await collegeService.updateCollege(col.id, { status: nextStatus })
      showToast(`${col.name} is now ${nextStatus}`, "success")
      await loadColleges(true)
    } catch (e) {
      showToast("Failed to update college status", "error")
    }
  }

  const handleDelete = async (col: College) => {
    if (!window.confirm(`Are you sure you want to delete ${col.name}?`)) return
    try {
      await collegeService.deleteCollege(col.id)
      showToast(`${col.shortName || col.name} deleted`, "success")
      await loadColleges(true)
    } catch (e) {
      showToast("Failed to delete college", "error")
    }
  }

  const handleSeedDefaults = async () => {
    try {
      const count = await collegeService.seedDefaultColleges()
      showToast(`Seeded ${count} default Kerala college presets into Firestore!`, "success")
      await loadColleges(true)
    } catch (e) {
      showToast("Failed to seed default colleges", "error")
    }
  }

  const filteredColleges = colleges.filter(c => {
    const matchesSearch =
      c.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      c.code.toLowerCase().includes(searchQuery.toLowerCase()) ||
      c.city.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (c.allowedDomains || []).some(d => d.includes(searchQuery.toLowerCase()))

    const matchesStatus = statusFilter === "all" || c.status === statusFilter
    return matchesSearch && matchesStatus
  })

  const activeCount = colleges.filter(c => c.status === "active").length
  const totalDomains = colleges.reduce((acc, c) => acc + (c.allowedDomains?.length || 0), 0)

  return (
    <div className="space-y-6">
      {/* Top Header & Actions */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl sm:text-2xl font-black text-gray-950 tracking-tight">
            Colleges & Campus Management
          </h1>
          <p className="text-xs sm:text-sm text-gray-500 font-medium">
            Onboard new campuses, configure allowed student email domains, and set local transit hubs.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={handleSeedDefaults}
            className="px-3.5 py-2 rounded-xl bg-gray-100 hover:bg-gray-200 text-gray-800 text-xs font-bold flex items-center gap-1.5 transition-all cursor-pointer"
            title="Seed standard Kerala engineering campuses into Firestore"
          >
            <MaterialIcon name="dataset" className="text-lg text-gray-600" />
            <span className="hidden sm:inline">Seed Default Campuses</span>
          </button>

          <button
            onClick={handleOpenAddModal}
            className="px-4 py-2 rounded-xl bg-[#C5FF00] hover:bg-[#b8ee00] text-black text-xs sm:text-sm font-extrabold flex items-center gap-2 shadow-xs transition-all cursor-pointer active:scale-95"
          >
            <MaterialIcon name="add" className="text-xl text-black" />
            <span>Onboard College</span>
          </button>
        </div>
      </div>

      {/* Metrics Row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3.5">
        <div className="bg-white p-4 rounded-2xl border border-gray-200 shadow-2xs">
          <p className="text-[11px] font-bold text-gray-400 uppercase tracking-wider">Total Onboarded</p>
          <p className="text-2xl font-black text-gray-950 mt-1">{colleges.length}</p>
        </div>
        <div className="bg-white p-4 rounded-2xl border border-gray-200 shadow-2xs">
          <p className="text-[11px] font-bold text-emerald-600 uppercase tracking-wider">Active Campuses</p>
          <p className="text-2xl font-black text-emerald-700 mt-1">{activeCount}</p>
        </div>
        <div className="bg-white p-4 rounded-2xl border border-gray-200 shadow-2xs">
          <p className="text-[11px] font-bold text-blue-600 uppercase tracking-wider">Verified Domains</p>
          <p className="text-2xl font-black text-blue-700 mt-1">{totalDomains}</p>
        </div>
        <div className="bg-white p-4 rounded-2xl border border-gray-200 shadow-2xs">
          <p className="text-[11px] font-bold text-purple-600 uppercase tracking-wider">Active State</p>
          <p className="text-2xl font-black text-purple-700 mt-1">Kerala</p>
        </div>
      </div>

      {/* Search & Filter Control Bar */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-3 bg-white p-3 rounded-2xl border border-gray-200 shadow-2xs">
        <div className="relative w-full sm:w-80">
          <MaterialIcon name="search" className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 text-lg" />
          <input
            type="text"
            placeholder="Search college, code, or domain..."
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            className="w-full pl-9 pr-4 py-2 bg-gray-50 border border-gray-200 rounded-xl text-xs sm:text-sm font-medium focus:outline-none focus:border-black"
          />
        </div>

        <div className="flex items-center gap-1.5 w-full sm:w-auto">
          {["all", "active", "onboarding", "paused"].map(status => (
            <button
              key={status}
              onClick={() => setStatusFilter(status)}
              className={`px-3 py-1.5 rounded-xl text-xs font-bold capitalize transition-all cursor-pointer ${
                statusFilter === status
                  ? "bg-black text-[#C5FF00]"
                  : "bg-gray-100 text-gray-600 hover:bg-gray-200"
              }`}
            >
              {status}
            </button>
          ))}
        </div>
      </div>

      {/* College Directory List */}
      {isLoading ? (
        <div className="bg-white rounded-2xl p-12 border border-gray-200 text-center">
          <div className="w-8 h-8 border-3 border-black border-t-transparent rounded-full animate-spin mx-auto mb-3" />
          <p className="text-xs text-gray-500 font-medium">Loading dynamic college registry...</p>
        </div>
      ) : filteredColleges.length === 0 ? (
        <div className="bg-white rounded-2xl p-12 border border-gray-200 text-center space-y-3">
          <MaterialIcon name="school" className="text-4xl text-gray-300 mx-auto" />
          <p className="text-sm font-bold text-gray-800">No Colleges Found</p>
          <p className="text-xs text-gray-500">No campuses matched your search or status filter.</p>
          <button
            onClick={handleSeedDefaults}
            className="px-4 py-2 bg-black text-[#C5FF00] rounded-xl text-xs font-bold"
          >
            Seed Default Kerala Campuses
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredColleges.map(col => {
            const isActive = col.status === "active"
            const isPaused = col.status === "paused"

            return (
              <div
                key={col.id}
                className="bg-white rounded-2xl border border-gray-200 p-5 space-y-4 shadow-2xs hover:shadow-md transition-shadow flex flex-col justify-between"
              >
                <div>
                  {/* Top Badge & Code */}
                  <div className="flex items-center justify-between gap-2 mb-2">
                    <span className="px-2.5 py-0.5 rounded-lg bg-black text-[#C5FF00] font-mono text-[11px] font-black tracking-wider">
                      {col.code}
                    </span>

                    <button
                      onClick={() => handleToggleStatus(col)}
                      className={`px-2.5 py-0.5 rounded-full text-[10px] font-extrabold uppercase tracking-wider cursor-pointer border transition-colors ${
                        isActive
                          ? "bg-emerald-50 text-emerald-800 border-emerald-200 hover:bg-emerald-100"
                          : isPaused
                          ? "bg-rose-50 text-rose-800 border-rose-200 hover:bg-rose-100"
                          : "bg-amber-50 text-amber-800 border-amber-200 hover:bg-amber-100"
                      }`}
                    >
                      {col.status}
                    </button>
                  </div>

                  {/* College Name & Location */}
                  <h3 className="font-extrabold text-gray-950 text-base leading-tight truncate" title={col.name}>
                    {col.name}
                  </h3>
                  <p className="text-xs text-gray-500 font-medium flex items-center gap-1 mt-1">
                    <MaterialIcon name="location_on" className="text-sm text-gray-400" />
                    <span>{col.city}, {col.state}</span>
                  </p>

                  {/* Domains */}
                  <div className="mt-3.5 space-y-1">
                    <p className="text-[10px] font-extrabold uppercase text-gray-400 tracking-wider">Student Email Domains</p>
                    <div className="flex flex-wrap gap-1">
                      {(col.allowedDomains && col.allowedDomains.length > 0) ? (
                        col.allowedDomains.map(d => (
                          <span key={d} className="px-2 py-0.5 rounded-md bg-blue-50 text-blue-700 font-mono text-[11px] font-semibold">
                            @{d}
                          </span>
                        ))
                      ) : (
                        <span className="text-xs text-gray-400 italic">No domain restriction</span>
                      )}
                    </div>
                  </div>

                  {/* Departments */}
                  <div className="mt-3.5 space-y-1">
                    <p className="text-[10px] font-extrabold uppercase text-gray-400 tracking-wider">
                      Branches / Departments ({col.departments?.length || 0})
                    </p>
                    <div className="flex flex-wrap gap-1 max-h-16 overflow-y-auto">
                      {(col.departments || []).map(dept => (
                        <span key={dept.code} className="px-2 py-0.5 rounded-md bg-gray-100 text-gray-700 font-mono text-[10px] font-bold">
                          {dept.code}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>

                {/* Card Actions Footer */}
                <div className="pt-3 border-t border-gray-100 flex items-center justify-between text-xs">
                  <button
                    onClick={() => handleOpenEditModal(col)}
                    className="px-3 py-1.5 rounded-xl bg-gray-100 hover:bg-gray-200 text-gray-800 font-bold flex items-center gap-1 cursor-pointer transition-colors"
                  >
                    <MaterialIcon name="edit" className="text-sm text-gray-600" />
                    <span>Edit Campus</span>
                  </button>

                  <button
                    onClick={() => handleDelete(col)}
                    className="p-1.5 text-gray-400 hover:text-rose-600 rounded-lg hover:bg-rose-50 transition-colors cursor-pointer"
                    title="Delete college"
                  >
                    <MaterialIcon name="delete" className="text-lg" />
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Add / Edit College Modal */}
      {isModalOpen && (
        <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-3xl max-w-lg w-full p-6 space-y-5 shadow-2xl border border-gray-100 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between border-b border-gray-100 pb-3">
              <h3 className="font-extrabold text-lg text-gray-950">
                {editingCollege ? "Edit College Configuration" : "Onboard New College"}
              </h3>
              <button
                onClick={() => setIsModalOpen(false)}
                className="w-8 h-8 rounded-full bg-gray-100 hover:bg-gray-200 flex items-center justify-center cursor-pointer"
              >
                <MaterialIcon name="close" className="text-lg text-gray-600" />
              </button>
            </div>

            <form onSubmit={handleSave} className="space-y-4">
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="block text-xs font-bold text-gray-700 mb-1">Code *</label>
                  <input
                    type="text"
                    required
                    placeholder="CET"
                    value={formData.code}
                    onChange={e => setFormData(prev => ({ ...prev, code: e.target.value }))}
                    className="w-full px-3 py-2 bg-gray-50 border border-gray-200 rounded-xl text-xs font-mono uppercase font-bold"
                  />
                </div>
                <div className="col-span-2">
                  <label className="block text-xs font-bold text-gray-700 mb-1">Short Name</label>
                  <input
                    type="text"
                    placeholder="CET Trivandrum"
                    value={formData.shortName}
                    onChange={e => setFormData(prev => ({ ...prev, shortName: e.target.value }))}
                    className="w-full px-3 py-2 bg-gray-50 border border-gray-200 rounded-xl text-xs font-medium"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-bold text-gray-700 mb-1">Full College Name *</label>
                <input
                  type="text"
                  required
                  placeholder="College of Engineering Trivandrum (CET)"
                  value={formData.name}
                  onChange={e => setFormData(prev => ({ ...prev, name: e.target.value }))}
                  className="w-full px-3 py-2 bg-gray-50 border border-gray-200 rounded-xl text-xs font-medium"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-bold text-gray-700 mb-1">City *</label>
                  <input
                    type="text"
                    required
                    placeholder="Thiruvananthapuram"
                    value={formData.city}
                    onChange={e => setFormData(prev => ({ ...prev, city: e.target.value }))}
                    className="w-full px-3 py-2 bg-gray-50 border border-gray-200 rounded-xl text-xs font-medium"
                  />
                </div>
                <div>
                  <label className="block text-xs font-bold text-gray-700 mb-1">Status</label>
                  <select
                    value={formData.status}
                    onChange={e => setFormData(prev => ({ ...prev, status: e.target.value as any }))}
                    className="w-full px-3 py-2 bg-gray-50 border border-gray-200 rounded-xl text-xs font-bold"
                  >
                    <option value="active">Active (Live)</option>
                    <option value="onboarding">Onboarding</option>
                    <option value="paused">Paused</option>
                  </select>
                </div>
              </div>

              <div>
                <label className="block text-xs font-bold text-gray-700 mb-1">
                  Allowed Student Email Domains (comma-separated)
                </label>
                <input
                  type="text"
                  placeholder="cet.ac.in, student.cet.ac.in"
                  value={formData.allowedDomains}
                  onChange={e => setFormData(prev => ({ ...prev, allowedDomains: e.target.value }))}
                  className="w-full px-3 py-2 bg-gray-50 border border-gray-200 rounded-xl text-xs font-mono"
                />
                <p className="text-[10px] text-gray-400 mt-1">Students registering with these domains will auto-match this college.</p>
              </div>

              <div>
                <label className="block text-xs font-bold text-gray-700 mb-1">Campus Location Name</label>
                <input
                  type="text"
                  placeholder="CET Main Campus, Sreekaryam"
                  value={formData.locationName}
                  onChange={e => setFormData(prev => ({ ...prev, locationName: e.target.value }))}
                  className="w-full px-3 py-2 bg-gray-50 border border-gray-200 rounded-xl text-xs font-medium"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-bold text-gray-700 mb-1">Latitude</label>
                  <input
                    type="text"
                    placeholder="8.5458"
                    value={formData.latitude}
                    onChange={e => setFormData(prev => ({ ...prev, latitude: e.target.value }))}
                    className="w-full px-3 py-2 bg-gray-50 border border-gray-200 rounded-xl text-xs font-mono"
                  />
                </div>
                <div>
                  <label className="block text-xs font-bold text-gray-700 mb-1">Longitude</label>
                  <input
                    type="text"
                    placeholder="76.9032"
                    value={formData.longitude}
                    onChange={e => setFormData(prev => ({ ...prev, longitude: e.target.value }))}
                    className="w-full px-3 py-2 bg-gray-50 border border-gray-200 rounded-xl text-xs font-mono"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-bold text-gray-700 mb-1">
                  Department / Branch Codes (comma-separated)
                </label>
                <textarea
                  rows={2}
                  placeholder="CSE, ECE, EEE, ME, CE, ARCH, MCA"
                  value={formData.departments}
                  onChange={e => setFormData(prev => ({ ...prev, departments: e.target.value }))}
                  className="w-full px-3 py-2 bg-gray-50 border border-gray-200 rounded-xl text-xs font-mono"
                />
              </div>

              <div className="pt-3 border-t border-gray-100 flex items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setIsModalOpen(false)}
                  className="px-4 py-2 rounded-xl bg-gray-100 text-gray-700 text-xs font-bold"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSaving}
                  className="px-5 py-2 rounded-xl bg-black text-[#C5FF00] text-xs font-extrabold shadow-xs active:scale-95 transition-all cursor-pointer"
                >
                  {isSaving ? "Saving..." : editingCollege ? "Update College" : "Create College"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
