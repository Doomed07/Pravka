package core_http_types

import (
	"encoding/json"
	"reflect"
	"testing"
)

// Nullable различает три состояния JSON-поля, на этом построена вся
// логика PATCH: поле отсутствует / поле = null / поле = значение.
func TestNullable_UnmarshalJSON(t *testing.T) {
	type request struct {
		Rating Nullable[int] `json:"rating"`
	}

	tests := []struct {
		name      string
		body      string
		wantSet   bool
		wantValue *int
		wantErr   bool
	}{
		{name: "field absent", body: `{}`, wantSet: false, wantValue: nil},
		{name: "field is null", body: `{"rating": null}`, wantSet: true, wantValue: nil},
		{name: "field has value", body: `{"rating": 80}`, wantSet: true, wantValue: new(80)},
		{name: "wrong type", body: `{"rating": "80"}`, wantErr: true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var got request
			gotErr := json.Unmarshal([]byte(tt.body), &got)

			if tt.wantErr {
				if gotErr == nil {
					t.Fatal("Unmarshal() succeeded unexpectedly")
				}
				return
			}

			if gotErr != nil {
				t.Fatalf("Unmarshal() failed: %v", gotErr)
			}
			if got.Rating.Set != tt.wantSet {
				t.Errorf("Set = %v, want %v", got.Rating.Set, tt.wantSet)
			}
			if !reflect.DeepEqual(got.Rating.Value, tt.wantValue) {
				t.Errorf("Value = %v, want %v", got.Rating.Value, tt.wantValue)
			}

			// ToDomain должен перенести оба поля без изменений
			domain := got.Rating.ToDomain()
			if domain.Set != got.Rating.Set || !reflect.DeepEqual(domain.Value, got.Rating.Value) {
				t.Errorf("ToDomain() = %+v, want Set=%v Value=%v", domain, got.Rating.Set, got.Rating.Value)
			}
		})
	}
}
