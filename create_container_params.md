{
    "create_container":
    {
        "required_parameters": 
        {
            "config": "Container.Config_info",
            "cpu_number": "int",
            "memory": "number (GB)",
            "gpu_list": "list[int] | None",
            "image": "str",
            "port": "int",
            "user_name": "str"
        }
        "returned_parameters": 
        {
            "container_id": "str",
            "container_name": "str"
        }
    }
}

###########

{
    "remove_container":
    {
        "required_parameters":
        {
            "container_id": "str"
        },
        "returned_parameters":
        {
            "result_code": "int (RemoveContinaerReturn.SUCCESS | RemoveContinaerReturn.NOTFOUND | RemoveContinaerReturn.FAILED)"
        }
    }
}

###########

{
    "add_collaborator":
    {
        "required_parameters":
        {
            "container_id": "int",
            "user_name": "str",
            "role": "ROLE"
        },
        "returned_parameters":
        {
            "success": "bool"
        }
    }
}

###########

{
    "remove_collaborator":
    {
        "required_parameters":
        {
            "container_id": "str",
            "user_name": "str"
        },
        "returned_parameters":
        {
            "success": "bool"
        }
    }
}

###########

{
    "update_role":
    {
        "required_parameters":
        {
            "container_id": "str",
            "user_name": "str",
            "updated_role": "str"
        },
        "returned_parameters":
        {
            "success": "bool"
        }
    }
}
