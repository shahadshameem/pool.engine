const admin = require("firebase-admin");

if (!admin.apps.length) {
  admin.initializeApp({
    projectId: process.env.GCLOUD_PROJECT || "waymate-v3"
  });
}

const db = admin.firestore();

async function inspect() {
  console.log("==========================================");
  console.log("FIRESTORE ADMIN INSPECTION (waymate-v3)");
  console.log("==========================================\n");

  // 1. RIDES Collection
  const ridesSnap = await db.collection("rides").get();
  console.log(`[1] RIDES COLLECTION (Total documents: ${ridesSnap.docs.length})`);

  if (ridesSnap.empty) {
    console.log("   --> NO RIDES EXIST IN FIRESTORE DATABASE AT THIS TIME.");
  } else {
    ridesSnap.docs.forEach((docSnap, i) => {
      const data = docSnap.data();
      console.log(`\n   --- Ride #${i + 1} ---`);
      console.log(`   Doc ID:        ${docSnap.id}`);
      console.log(`   Owner ID (uid): ${data.ownerId}`);
      console.log(`   Route:         ${data.from} -> ${data.to}`);
      console.log(`   Date:          ${data.date}`);
      console.log(`   Time:          ${data.departureTime}`);
      console.log(`   Gender Policy: ${data.genderPolicy}`);
      console.log(`   Status:        ${data.status}`);
      console.log(`   Seats:         ${data.availableSeats}/${data.totalSeats}`);
      console.log(`   fromLocation:  `, data.fromLocation);
      console.log(`   toLocation:    `, data.toLocation);
      console.log(`   createdAt:     `, data.createdAt?.toDate ? data.createdAt.toDate() : data.createdAt);
    });
  }

  const ownerIds = ridesSnap.docs.map(d => d.data().ownerId);
  const uniqueOwnerIds = new Set(ownerIds);
  console.log(`\n   Total Ride Documents:     ${ridesSnap.docs.length}`);
  console.log(`   Unique Owner UIDs Count:  ${uniqueOwnerIds.size}`);
  if (uniqueOwnerIds.size > 0) {
    console.log(`   Unique Owner UIDs List:  `, Array.from(uniqueOwnerIds));
  }

  // 2. USERS Collection
  const usersSnap = await db.collection("users").get();
  console.log(`\n[2] USERS COLLECTION (Total documents: ${usersSnap.docs.length})`);
  usersSnap.docs.forEach((docSnap) => {
    const data = docSnap.data();
    console.log(`   User UID: ${docSnap.id} | Name: "${data.name}" | Gender: "${data.gender}" | Email: "${data.email}"`);
  });

  // 3. NOTIFICATIONS Collection
  const notifSnap = await db.collection("notifications").get();
  console.log(`\n[3] NOTIFICATIONS COLLECTION (Total documents: ${notifSnap.docs.length})`);
  notifSnap.docs.forEach((docSnap) => {
    const data = docSnap.data();
    console.log(`   Notif ID: ${docSnap.id} | Type: ${data.type} | Target userId: ${data.userId} | Title: "${data.title}"`);
  });

  console.log("\n==========================================");
  process.exit(0);
}

inspect().catch(err => {
  console.error("Admin inspection error:", err);
  process.exit(1);
});
