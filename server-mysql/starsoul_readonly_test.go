package main

import (
	"reflect"
	"sync"
	"testing"
)

func TestStarSoulStatReadsDoNotNormalizeOrAllocateSessionState(t *testing.T) {
	loadOnlineTablesForTest(t)
	empty := newSession()
	starSoulBonus(empty)
	starSoulSuitBonus(empty)
	if empty.starSoul != nil {
		t.Fatal("reading attributes initialized the player's star-soul inventory")
	}
	bag := &starSoulBag{
		Items: map[int64]*starSoulItem{
			1: {ID: 1, TypeID: 1001, PosType: 0, Main: 1105, Level: 1},
			2: {ID: 2, TypeID: 1001, PosType: 1, Main: 1106, IsUsed: true},
		},
		Used: []int64{1, 1, 999, 2}, // wrong-slot and missing entries are ignored.
	}
	ss := newSession()
	ss.starSoul = bag
	wantBonus, wantSuit := starSoulBonus(ss), starSoulSuitBonus(ss)
	var workers sync.WaitGroup
	for i := 0; i < 8; i++ {
		workers.Add(1)
		go func() {
			defer workers.Done()
			for j := 0; j < 30; j++ {
				if !reflect.DeepEqual(starSoulBonus(ss), wantBonus) || !reflect.DeepEqual(starSoulSuitBonus(ss), wantSuit) {
					t.Error("concurrent attribute reads changed the result")
					return
				}
			}
		}()
	}
	workers.Wait()
	if !reflect.DeepEqual(bag.Used, []int64{1, 1, 999, 2}) || bag.Items[1].IsUsed || !bag.Items[2].IsUsed {
		t.Fatal("attribute calculation mutated inventory slots or IsUsed flags")
	}
	bag.normalize()
	if !reflect.DeepEqual(starSoulBonus(ss), wantBonus) || !reflect.DeepEqual(starSoulSuitBonus(ss), wantSuit) {
		t.Fatal("read-only validation disagrees with normalized inventory")
	}
}

func BenchmarkStarSoulDerivedAttributes(b *testing.B) {
	old := tables
	if err := loadDatatables("../datatable_json"); err != nil {
		b.Fatal(err)
	}
	defer func() { tables = old }()
	ss := newSession()
	ss.jobID, ss.level = 1, 100
	ss.starSoul = newStarSoulBag()
	for slot := 0; slot < starSoulSlotCount; slot++ {
		id := int64(slot + 1)
		ss.starSoul.Items[id] = &starSoulItem{ID: id, TypeID: 1001, PosType: int32(slot), Main: 1105, Level: 5, IsUsed: true}
		ss.starSoul.Used[slot] = id
	}
	b.ReportAllocs()
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		if ss.playerMaxHp() <= 0 {
			b.Fatal("invalid derived HP")
		}
	}
}
