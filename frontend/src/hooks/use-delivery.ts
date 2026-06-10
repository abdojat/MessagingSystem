import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/services/api/client";
import type {
  DeliveryListResponse,
  DeliveryRetryResponse,
  DeliveryStatsResponse,
} from "@/types/api";

const deliveryQueryKey = ["/admin/delivery"];

export function useDeliveryStats() {
  return useQuery({
    queryKey: [...deliveryQueryKey, "stats"],
    queryFn: () => apiClient<DeliveryStatsResponse>("/admin/delivery/stats"),
  });
}

export function useFailedDeliveries() {
  return useQuery({
    queryKey: [...deliveryQueryKey, "failed"],
    queryFn: () => apiClient<DeliveryListResponse>("/admin/delivery/failed"),
  });
}

export function useDeadLetteredDeliveries() {
  return useQuery({
    queryKey: [...deliveryQueryKey, "dead-lettered"],
    queryFn: () => apiClient<DeliveryListResponse>("/admin/delivery/dead-lettered"),
  });
}

function useInvalidateDeliveryQueries() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: deliveryQueryKey });
}

export function useRetryDelivery() {
  const invalidateDeliveryQueries = useInvalidateDeliveryQueries();
  return useMutation({
    mutationFn: (outboxId: string) =>
      apiClient<DeliveryRetryResponse>(`/admin/delivery/${outboxId}/retry`, {
        method: "POST",
      }),
    onSuccess: invalidateDeliveryQueries,
  });
}

export function useRetryAllDeliveries() {
  const invalidateDeliveryQueries = useInvalidateDeliveryQueries();
  return useMutation({
    mutationFn: () =>
      apiClient<DeliveryRetryResponse>("/admin/delivery/retry-all", {
        method: "POST",
      }),
    onSuccess: invalidateDeliveryQueries,
  });
}
