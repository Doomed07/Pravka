package auth_transport_http

import core_domain "github.com/Doomed07/Pravka/internal/core/domain"

type UserDTOResponse struct {
	ID       int    `json:"id" example:"1"`
	Username string `json:"username" example:"book_worm07"`
	Email    string `json:"email" example:"lol@mail.com"`
}

func userDTOFromDomain(user core_domain.User) UserDTOResponse {
	return UserDTOResponse{
		ID:       user.ID,
		Username: user.Username,
		Email:    user.Email,
	}
}
